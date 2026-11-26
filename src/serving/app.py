"""Flask REST API for Pakistan AirWatch AI.

Required endpoints (course specification section 3.8):

    GET  /health       service and model health
    GET  /model-info   model version and metadata
    POST /predict      predictions for a list of cities

Application endpoints consumed by the React dashboard:

    GET  /api/cities             the 134 reference cities
    GET  /api/forecast           map layer for one horizon
    GET  /api/history/<city_id>  observed history + forecasts
    GET  /api/legend             AQI bands, so colours never drift
    GET  /api/stats              national summary tiles

Operational:

    GET  /metrics      Prometheus exposition

Security posture: request bodies are validated before use, request
bodies are never logged, the city list per request is capped, and
errors return structured JSON rather than stack traces.
"""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import pandas as pd
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_flask_exporter import PrometheusMetrics

from src.config import MODEL_CFG, settings
from src.data.cities import load_cities
from src.serving import aqi
from src.serving.live_features import get_store
from src.serving.model_loader import ModelLoader, ModelNotReadyError
from src.serving.schemas import (
    validate_forecast_query,
    validate_history_query,
    validate_predict_request,
)

# ──────────────────────────────────────────────────────────────
# Logging — structured, and deliberately free of request bodies
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s",'
    '"logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("airwatch.api")


def create_app(registry: CollectorRegistry | None = None) -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB request cap

    CORS(app, origins=settings.cors_origins, supports_credentials=False)

    # Each app instance gets its own collector registry. Prometheus
    # metric names are globally unique within a registry, so sharing
    # the default one would make a second create_app() call — which
    # every API test performs — raise "Duplicated timeseries".
    registry = registry or CollectorRegistry(auto_describe=True)

    metrics = PrometheusMetrics(app, registry=registry, group_by="endpoint")
    metrics.info(
        "airwatch_app_info",
        "Pakistan AirWatch AI",
        version=settings.app_version,
    )

    # ── custom Prometheus metrics ─────────────────────────────
    PREDICTIONS = Counter(
        "airwatch_predictions_total",
        "Predictions served",
        ["horizon", "status"],
        registry=registry,
    )
    PRED_LATENCY = Histogram(
        "airwatch_prediction_latency_seconds",
        "End-to-end prediction latency",
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=registry,
    )
    PRED_VALUE = Histogram(
        "airwatch_predicted_pm25_ugm3",
        "Distribution of predicted PM2.5 — an early drift signal",
        buckets=(10, 25, 35, 55, 75, 100, 150, 200, 300, 500),
        registry=registry,
    )
    DQ_FAILURES = Counter(
        "airwatch_data_quality_failures_total",
        "Validation failures",
        ["check"],
        registry=registry,
    )
    MODEL_INFO = Gauge(
        "airwatch_model_version_info",
        "Model version currently serving",
        ["version", "stage", "algorithm"],
        registry=registry,
    )
    UPSTREAM_AGE = Gauge(
        "airwatch_upstream_data_age_seconds",
        "Age of the cached upstream data",
        registry=registry,
    )

    # ── model ─────────────────────────────────────────────────
    loader = ModelLoader()
    app.extensions["model_loader"] = loader
    if loader.is_ready():
        MODEL_INFO.labels(
            version=loader.version,
            stage=loader.stage,
            algorithm=loader.algorithm,
        ).set(1)

    # ── request lifecycle ─────────────────────────────────────
    @app.before_request
    def _start_timer() -> None:
        g.request_id = uuid.uuid4().hex[:12]
        g.start_time = time.perf_counter()

    @app.after_request
    def _log_request(response):
        duration_ms = (time.perf_counter() - getattr(g, "start_time", 0)) * 1000
        # Path, status and timing only. Never the body.
        log.info(
            "rid=%s %s %s -> %s %.1fms",
            getattr(g, "request_id", "-"),
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        response.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    # ──────────────────────────────────────────────────────────
    # Required endpoints
    # ──────────────────────────────────────────────────────────
    @app.get("/health")
    def health():
        store = get_store()
        age = store.age_seconds
        if age is not None:
            UPSTREAM_AGE.set(age)

        model_ready = loader.is_ready()
        payload = {
            "status": "healthy" if model_ready else "degraded",
            "model_loaded": model_ready,
            "model_version": loader.version if model_ready else None,
            "app_version": settings.app_version,
            "upstream_cache": store.status(),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if not model_ready:
            payload["reason"] = loader.load_error or "no model loaded"
        return jsonify(payload), (200 if model_ready else 503)

    @app.get("/model-info")
    def model_info():
        return jsonify(loader.info()), 200

    @app.post("/predict")
    def predict():
        payload = request.get_json(silent=True)
        if payload is None:
            DQ_FAILURES.labels(check="malformed_json").inc()
            return (
                jsonify(
                    {
                        "error": "invalid_json",
                        "message": "Request body must be valid JSON with "
                        "Content-Type: application/json",
                    }
                ),
                400,
            )

        result = validate_predict_request(payload)
        if not result.ok:
            DQ_FAILURES.labels(check="request_schema").inc()
            return jsonify(result.as_response()), 422

        # Separate "this city does not exist" from "the service is
        # broken". Both used to surface as 503, which told a monitoring
        # system the API was down when it was perfectly healthy.
        known = _known_city_ids()
        wanted = [r for r in result.cleaned if r["city_id"] in known]
        unknown = [
            {
                "city_id": r["city_id"],
                "horizon": r["horizon"],
                "pm2_5_pred": None,
                "error": "unknown city_id; see GET /api/cities",
            }
            for r in result.cleaned
            if r["city_id"] not in known
        ]

        if not wanted:
            for item in unknown:
                PREDICTIONS.labels(
                    horizon=str(item["horizon"]), status="unknown_city"
                ).inc()
            return (
                jsonify(
                    {
                        "model_version": loader.version,
                        "model_name": loader.name,
                        "generated_at": datetime.now(UTC).isoformat(),
                        "count": len(unknown),
                        "predictions": unknown,
                    }
                ),
                200,
            )

        try:
            with PRED_LATENCY.time():
                predictions = loader.predict(
                    wanted,
                    feature_provider=lambda ids: get_store().latest_features(ids),
                )
        except ModelNotReadyError as exc:
            PREDICTIONS.labels(horizon="any", status="unavailable").inc()
            return (
                jsonify(
                    {
                        "error": "model_unavailable",
                        "message": str(exc),
                        "request_id": g.request_id,
                    }
                ),
                503,
            )
        except ValueError as exc:
            DQ_FAILURES.labels(check="no_features").inc()
            return (
                jsonify(
                    {
                        "error": "no_data",
                        "message": str(exc),
                        "request_id": g.request_id,
                    }
                ),
                503,
            )
        except Exception:
            log.exception("rid=%s prediction failed", g.request_id)
            PREDICTIONS.labels(horizon="any", status="error").inc()
            return (
                jsonify(
                    {
                        "error": "internal_error",
                        "message": "Prediction failed. Quote the request id "
                        "when reporting this.",
                        "request_id": g.request_id,
                    }
                ),
                500,
            )

        predictions = predictions + unknown

        for item in predictions:
            if item.get("pm2_5_pred") is not None:
                status = "ok"
                PRED_VALUE.observe(item["pm2_5_pred"])
            elif "unknown city_id" in str(item.get("error", "")):
                status = "unknown_city"
            else:
                status = "missing"
            PREDICTIONS.labels(horizon=str(item["horizon"]), status=status).inc()

        return (
            jsonify(
                {
                    "model_version": loader.version,
                    "model_name": loader.name,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "count": len(predictions),
                    "predictions": predictions,
                    "attribution": "Source data © Open-Meteo.com (CC BY 4.0)",
                    "disclaimer": "Academic prototype. Not an official "
                    "public-health warning system.",
                }
            ),
            200,
        )

    # ──────────────────────────────────────────────────────────
    # Dashboard endpoints
    # ──────────────────────────────────────────────────────────
    @app.get("/api/cities")
    def api_cities():
        cities = load_cities()
        return jsonify(
            {
                "count": len(cities),
                "cities": cities.to_dict("records"),
                "provinces": sorted(cities["province"].unique().tolist()),
            }
        ), 200

    @app.get("/api/forecast")
    def api_forecast():
        check = validate_forecast_query(request.args.to_dict())
        if not check.ok:
            return jsonify(check.as_response()), 422

        horizon = check.cleaned["horizon"]
        cities = load_cities()
        if check.cleaned.get("province"):
            cities = cities[cities["province"] == check.cleaned["province"]]

        requests_list = [
            {"city_id": cid, "horizon": horizon} for cid in cities["city_id"]
        ]

        try:
            predictions = loader.predict(
                requests_list,
                feature_provider=lambda ids: get_store().latest_features(ids),
            )
        except (ModelNotReadyError, ValueError) as exc:
            return (
                jsonify({"error": "unavailable", "message": str(exc)}),
                503,
            )

        meta = cities.set_index("city_id")[
            [
                "city_name",
                "province",
                "latitude",
                "longitude",
                "population",
                # Elevation drives one of the clearest physical signals
                # in this dataset: highland cities sit in thinner,
                # better-ventilated air while the Indus plain traps
                # smog under winter inversions. The dashboard plots it.
                "elevation_m",
            ]
        ].to_dict("index")

        enriched = []
        for p in predictions:
            m = meta.get(p["city_id"], {})
            enriched.append({**p, **m})

        if check.cleaned["format"] == "geojson":
            return jsonify(_to_geojson(enriched)), 200

        return (
            jsonify(
                {
                    "horizon": horizon,
                    "model_version": loader.version,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "count": len(enriched),
                    "features": enriched,
                }
            ),
            200,
        )

    @app.get("/api/history/<city_id>")
    def api_history(city_id: str):
        check = validate_history_query(request.args.to_dict())
        if not check.ok:
            return jsonify(check.as_response()), 422

        city_id = city_id.strip().lower()[:64]
        cities = load_cities()
        row = cities[cities["city_id"] == city_id]
        if row.empty:
            return (
                jsonify({"error": "not_found", "message": f"Unknown city '{city_id}'"}),
                404,
            )

        store = get_store()
        try:
            observed = store.recent_observations(city_id, days=check.cleaned["days"])
            provider = store.provider_forecast(city_id)
        except Exception as exc:
            log.exception("rid=%s history failed", g.request_id)
            return jsonify({"error": "unavailable", "message": str(exc)}), 503

        # History is still useful without live predictions, so a model
        # or upstream problem must not fail the whole response.
        model_preds = []
        with contextlib.suppress(ModelNotReadyError, ValueError):
            model_preds = loader.predict(
                [{"city_id": city_id, "horizon": h} for h in MODEL_CFG["horizons"]],
                feature_provider=lambda ids: store.latest_features(ids),
            )

        return (
            jsonify(
                {
                    "city": row.iloc[0].to_dict(),
                    "observed": _series(observed),
                    "provider_forecast": _series(provider),
                    "model_predictions": model_preds,
                    "generated_at": datetime.now(UTC).isoformat(),
                }
            ),
            200,
        )

    @app.get("/api/legend")
    def api_legend():
        return jsonify({"standard": aqi.STANDARD, "bands": aqi.legend()}), 200

    @app.get("/api/stats")
    def api_stats():
        """National summary tiles for the dashboard header."""
        try:
            latest = get_store().latest_features()
        except Exception as exc:
            return jsonify({"error": "unavailable", "message": str(exc)}), 503

        if latest.empty or "pm2_5" not in latest.columns:
            return jsonify({"error": "no_data"}), 503

        cities = load_cities().set_index("city_id")
        vals = latest.set_index("city_id")["pm2_5"].dropna()
        if vals.empty:
            return jsonify({"error": "no_data"}), 503

        worst = vals.idxmax()
        best = vals.idxmin()

        def extreme(city_id: str) -> dict:
            """The extremes carry their context, not just a number.

            A reader asking "how bad is the worst city?" immediately asks
            "and how many people live there?", so the answer ships with
            the question rather than needing a second request.
            """
            row = cities.loc[city_id]
            value = float(vals[city_id])
            out = {
                "city_id": city_id,
                "city_name": row["city_name"],
                "province": row["province"],
                "pm2_5": round(value, 1),
                **aqi.describe(value),
            }
            for field in ("population", "elevation_m"):
                raw = row.get(field)
                if raw is not None and pd.notna(raw):
                    out[field] = int(raw)
            return out

        bands: dict[str, int] = {}
        for v in vals:
            cat = aqi.aqi_category(aqi.pm25_to_aqi(float(v)))
            if cat:
                bands[cat.name] = bands.get(cat.name, 0) + 1

        return (
            jsonify(
                {
                    "cities_reporting": int(len(vals)),
                    "national_mean_pm25": round(float(vals.mean()), 1),
                    "national_median_pm25": round(float(vals.median()), 1),
                    "worst": extreme(worst),
                    "best": extreme(best),
                    "category_counts": bands,
                    "observed_at": str(latest["timestamp"].max()),
                    "generated_at": datetime.now(UTC).isoformat(),
                }
            ),
            200,
        )

    # ──────────────────────────────────────────────────────────
    # Error handlers — structured JSON, never HTML or a traceback
    # ──────────────────────────────────────────────────────────
    @app.errorhandler(400)
    def _bad_request(_):
        return jsonify({"error": "bad_request"}), 400

    @app.errorhandler(404)
    def _not_found(_):
        return jsonify({"error": "not_found", "message": "Unknown endpoint"}), 404

    @app.errorhandler(405)
    def _not_allowed(_):
        return (
            jsonify(
                {
                    "error": "method_not_allowed",
                    "allowed": list(request.url_rule.methods)
                    if request.url_rule
                    else [],
                }
            ),
            405,
        )

    @app.errorhandler(413)
    def _too_large(_):
        return jsonify({"error": "payload_too_large", "limit_bytes": 1048576}), 413

    @app.errorhandler(500)
    def _server_error(_):
        return (
            jsonify(
                {
                    "error": "internal_error",
                    "request_id": getattr(g, "request_id", "-"),
                }
            ),
            500,
        )

    return app


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _known_city_ids() -> frozenset[str]:
    """The reference city list, cached — it never changes at runtime."""
    return frozenset(load_cities()["city_id"].astype(str))


def _series(df: pd.DataFrame) -> list[dict]:
    """Compact time series for charting."""
    if df is None or df.empty:
        return []
    cols = [
        c
        for c in (
            "timestamp",
            "pm2_5",
            "pm10",
            "ozone",
            "nitrogen_dioxide",
            "temperature_2m",
            "relative_humidity_2m",
            "wind_speed_10m",
        )
        if c in df.columns
    ]
    out = df[cols].copy()
    out["timestamp"] = out["timestamp"].astype(str)
    for c in cols:
        if c != "timestamp":
            out[c] = out[c].round(2)
    return out.where(pd.notna(out), None).to_dict("records")


def _to_geojson(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [f.get("longitude"), f.get("latitude")],
                },
                "properties": {
                    k: v for k, v in f.items() if k not in ("latitude", "longitude")
                },
            }
            for f in features
            if f.get("latitude") is not None
        ],
    }


app = create_app()


if __name__ == "__main__":
    # Development server only. Production uses Gunicorn (see Dockerfile).
    app.run(host=settings.api_host, port=settings.api_port, debug=False)
