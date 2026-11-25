"""API tests: endpoints, validation, error handling, metrics."""

from __future__ import annotations

import json


# ── required endpoints ────────────────────────────────────────
def test_health_returns_json(api_client):
    r = api_client.get("/health")
    assert r.status_code in (200, 503)
    body = r.get_json()
    assert "status" in body
    assert "model_loaded" in body
    assert "timestamp" in body


def test_health_reports_healthy_when_model_loaded(api_client):
    body = api_client.get("/health").get_json()
    assert body["model_loaded"] is True
    assert body["status"] == "healthy"


def test_model_info_contains_required_fields(api_client):
    body = api_client.get("/model-info").get_json()
    for field in (
        "model_name",
        "model_version",
        "stage",
        "algorithm",
        "features",
        "target",
        "horizons",
        "aqi_standard",
    ):
        assert field in body, f"/model-info is missing '{field}'"


def test_model_info_never_leaks_credentials(api_client):
    """A public endpoint must not expose tokens or connection strings."""
    raw = api_client.get("/model-info").get_data(as_text=True).lower()
    for secret in ("password", "token", "secret", "dagshub.com/", "postgresql://"):
        assert secret not in raw, f"/model-info leaked '{secret}'"


# ── /predict happy path ───────────────────────────────────────
def test_predict_valid_request(api_client):
    r = api_client.post(
        "/predict", json={"cities": [{"city_id": "lahore", "horizon": 24}]}
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["count"] == 1
    p = body["predictions"][0]
    assert p["city_id"] == "lahore"
    assert p["horizon"] == 24
    assert p["pm2_5_pred"] >= 0
    assert p["unit"] == "ug/m3"


def test_predict_includes_provenance(api_client):
    """Every value must say what produced it — an ethics requirement."""
    r = api_client.post("/predict", json={"cities": [{"city_id": "lahore"}]})
    p = r.get_json()["predictions"][0]
    assert p["source"] == "model_prediction"
    assert "model_version" in p
    assert "valid_time" in p
    assert "generated_at" in p


def test_predict_includes_aqi(api_client):
    r = api_client.post("/predict", json={"cities": [{"city_id": "lahore"}]})
    p = r.get_json()["predictions"][0]
    assert "aqi_us" in p
    assert "aqi_category" in p
    assert "US EPA" in p["aqi_standard"]


def test_predict_defaults_horizon_to_24(api_client):
    r = api_client.post("/predict", json={"cities": [{"city_id": "karachi"}]})
    assert r.get_json()["predictions"][0]["horizon"] == 24


def test_predict_multiple_cities(api_client):
    r = api_client.post(
        "/predict",
        json={
            "cities": [
                {"city_id": "lahore", "horizon": 1},
                {"city_id": "karachi", "horizon": 24},
            ]
        },
    )
    assert r.status_code == 200
    assert r.get_json()["count"] == 2


def test_predict_deduplicates_identical_entries(api_client):
    r = api_client.post(
        "/predict",
        json={
            "cities": [
                {"city_id": "lahore", "horizon": 24},
                {"city_id": "lahore", "horizon": 24},
            ]
        },
    )
    assert r.get_json()["count"] == 1


# ── /predict validation and errors ────────────────────────────
def test_predict_rejects_non_json_body(api_client):
    r = api_client.post("/predict", data="not json", content_type="application/json")
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_json"


def test_predict_rejects_missing_cities_key(api_client):
    r = api_client.post("/predict", json={"wrong": []})
    assert r.status_code == 422


def test_predict_rejects_empty_cities(api_client):
    r = api_client.post("/predict", json={"cities": []})
    assert r.status_code == 422


def test_predict_rejects_invalid_horizon(api_client):
    r = api_client.post(
        "/predict", json={"cities": [{"city_id": "lahore", "horizon": 999}]}
    )
    assert r.status_code == 422
    assert "horizon" in json.dumps(r.get_json()).lower()


def test_predict_rejects_too_many_cities(api_client):
    """Caps a cheap denial-of-service vector."""
    r = api_client.post(
        "/predict", json={"cities": [{"city_id": f"c{i}"} for i in range(500)]}
    )
    assert r.status_code == 422


def test_predict_rejects_oversized_city_id(api_client):
    r = api_client.post("/predict", json={"cities": [{"city_id": "x" * 500}]})
    assert r.status_code == 422


def test_predict_rejects_injection_characters(api_client):
    r = api_client.post(
        "/predict", json={"cities": [{"city_id": "lahore'; DROP TABLE--"}]}
    )
    assert r.status_code == 422


def test_predict_rejects_non_string_city_id(api_client):
    r = api_client.post("/predict", json={"cities": [{"city_id": 12345}]})
    assert r.status_code == 422


def test_predict_handles_unknown_city_gracefully(api_client):
    """An unknown city is reported per-entry, not as a 500."""
    r = api_client.post(
        "/predict", json={"cities": [{"city_id": "atlantis", "horizon": 24}]}
    )
    assert r.status_code == 200
    p = r.get_json()["predictions"][0]
    assert p["pm2_5_pred"] is None
    assert "error" in p


def test_predict_rejects_get_method(api_client):
    assert api_client.get("/predict").status_code == 405


# ── dashboard endpoints ───────────────────────────────────────
def test_cities_endpoint(api_client):
    body = api_client.get("/api/cities").get_json()
    assert body["count"] >= 100
    assert "provinces" in body
    assert len(body["cities"]) == body["count"]


def test_legend_endpoint(api_client):
    body = api_client.get("/api/legend").get_json()
    assert "US EPA" in body["standard"]
    assert len(body["bands"]) == 6
    assert body["bands"][0]["name"] == "Good"


def test_forecast_endpoint(api_client):
    r = api_client.get("/api/forecast?horizon=24")
    assert r.status_code == 200
    body = r.get_json()
    assert body["horizon"] == 24
    assert "features" in body


def test_forecast_geojson_format(api_client):
    body = api_client.get("/api/forecast?horizon=24&format=geojson").get_json()
    assert body["type"] == "FeatureCollection"
    if body["features"]:
        assert body["features"][0]["geometry"]["type"] == "Point"


def test_forecast_rejects_bad_horizon(api_client):
    assert api_client.get("/api/forecast?horizon=7").status_code == 422


def test_forecast_rejects_bad_format(api_client):
    assert api_client.get("/api/forecast?format=xml").status_code == 422


def test_history_endpoint(api_client):
    r = api_client.get("/api/history/lahore?days=3")
    assert r.status_code == 200
    body = r.get_json()
    assert body["city"]["city_id"] == "lahore"
    assert "observed" in body
    assert "model_predictions" in body


def test_history_unknown_city_returns_404(api_client):
    r = api_client.get("/api/history/atlantis")
    assert r.status_code == 404


def test_history_rejects_excessive_days(api_client):
    assert api_client.get("/api/history/lahore?days=9999").status_code == 422


# ── operational ───────────────────────────────────────────────
def test_metrics_endpoint_exposes_prometheus_format(api_client):
    r = api_client.get("/metrics")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "airwatch_predictions_total" in body
    assert "airwatch_prediction_latency_seconds" in body


def test_metrics_counter_increases_after_prediction(api_client):
    api_client.post("/predict", json={"cities": [{"city_id": "lahore"}]})
    body = api_client.get("/metrics").get_data(as_text=True)
    assert 'airwatch_predictions_total{horizon="24",status="ok"}' in body


def test_unknown_route_returns_json_404(api_client):
    r = api_client.get("/does-not-exist")
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_found"


def test_security_headers_present(api_client):
    r = api_client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in r.headers


def test_every_response_is_json(api_client):
    for path in (
        "/health",
        "/model-info",
        "/api/cities",
        "/api/legend",
        "/does-not-exist",
    ):
        r = api_client.get(path)
        assert r.content_type.startswith("application/json"), path
