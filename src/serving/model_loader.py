"""Model loading and prediction for the serving layer.

Two sources, chosen by the MODEL_SOURCE environment variable:

* ``registry`` — pull ``models:/pm25-forecaster/Production`` from the
  MLflow Model Registry. This is how the deployed service picks up a
  promotion without a rebuild.
* ``local``    — load ``models/production/model.pkl`` from disk. Used in
  CI, in tests, and whenever the tracking server is unreachable.

The loader never raises at import time. If no model is available the
service still starts, ``/health`` reports ``degraded`` and ``/predict``
returns 503. A monitoring system can then see *why* the service is
unhealthy, which a crash-looping container cannot tell it.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.config import MODEL_CFG, PROJECT_ROOT, settings
from src.serving import aqi

log = logging.getLogger(__name__)


class ModelNotReadyError(RuntimeError):
    """Raised when a prediction is requested but no model is loaded."""


class ModelLoader:
    """Holds the active model and serves predictions from it."""

    def __init__(self, auto_load: bool = True) -> None:
        self._lock = threading.Lock()
        self.model: Any = None
        self.name: str = MODEL_CFG["registry"]["model_name"]
        self.version: str = "unknown"
        self.stage: str = "unknown"
        self.run_id: str = "unknown"
        self.algorithm: str = "unknown"
        self.trained_at: str | None = None
        self.feature_names: list[str] = []
        self.metrics: dict[str, float] = {}
        self.source: str = settings.model_source
        self.loaded_at: str | None = None
        self.load_error: str | None = None

        if auto_load:
            self.load()

    # ── loading ───────────────────────────────────────────────
    def load(self) -> bool:
        """(Re)load the model. Returns True on success."""
        with self._lock:
            try:
                if self.source == "registry":
                    self._load_from_registry()
                else:
                    self._load_from_disk()
                self.loaded_at = datetime.now(UTC).isoformat()
                self.load_error = None
                log.info(
                    "Model ready: %s v%s (%s) from %s",
                    self.name,
                    self.version,
                    self.algorithm,
                    self.source,
                )
                return True
            except Exception as exc:
                self.model = None
                self.load_error = f"{type(exc).__name__}: {exc}"
                log.error("Model load failed (%s): %s", self.source, exc)
                return False

    def _load_from_registry(self) -> None:
        import mlflow

        from src.models.tracking import configure

        configure()
        uri = f"models:/{self.name}/{settings.model_stage}"
        log.info("Loading %s ...", uri)
        self.model = mlflow.pyfunc.load_model(uri)

        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        versions = [
            v
            for v in client.search_model_versions(f"name='{self.name}'")
            if v.current_stage == settings.model_stage
        ]
        if versions:
            mv = versions[0]
            self.version = str(mv.version)
            self.stage = mv.current_stage
            self.run_id = mv.run_id
            run = client.get_run(mv.run_id)
            self.metrics = {k: round(float(v), 4) for k, v in run.data.metrics.items()}
            self.algorithm = run.data.tags.get("model_family", "unknown")
            self.trained_at = datetime.fromtimestamp(
                run.info.start_time / 1000, tz=UTC
            ).isoformat()
            try:
                art = mlflow.artifacts.load_dict(
                    f"runs:/{mv.run_id}/feature_names.json"
                )
                self.feature_names = art.get("feature_names", [])
            except Exception:
                log.debug("feature_names.json not available for this run")

    def _load_from_disk(self) -> None:
        base = Path(settings.local_model_path)
        if not base.is_absolute():
            base = PROJECT_ROOT / base

        candidates = [base / "model.pkl", *sorted(base.glob("**/model.pkl"))]
        model_file = next((p for p in candidates if p.exists()), None)
        if model_file is None:
            raise FileNotFoundError(
                f"No model.pkl under {base}. Train a model and run:\n"
                "  python -m src.models.registry export-production\n"
                "or copy a candidate from models/candidates/<run>/."
            )

        self.model = joblib.load(model_file)
        self.algorithm = type(self.model).__name__

        meta_file = model_file.parent / "metadata.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            self.version = str(meta.get("version", meta.get("run_name", "local")))
            self.stage = meta.get("stage", "local")
            self.run_id = meta.get("run_id", "local")
            self.metrics = {
                k: round(float(v), 4)
                for k, v in (meta.get("metrics") or {}).items()
                if isinstance(v, int | float)
            }
            self.feature_names = meta.get("feature_names", [])
            self.algorithm = meta.get("model_family", self.algorithm)
            self.trained_at = meta.get("exported_at")
        else:
            self.version = "local"
            self.stage = "local"

    # ── state ─────────────────────────────────────────────────
    def is_ready(self) -> bool:
        return self.model is not None

    def info(self) -> dict[str, Any]:
        """Payload for GET /model-info."""
        return {
            "model_name": self.name,
            "model_version": self.version,
            "stage": self.stage,
            "run_id": self.run_id,
            "algorithm": self.algorithm,
            "source": self.source,
            "trained_at": self.trained_at,
            "loaded_at": self.loaded_at,
            "n_features": len(self.feature_names),
            "features": self.feature_names[:80],
            "metrics": self.metrics,
            "target": MODEL_CFG["target"],
            "target_unit": MODEL_CFG["target_unit"],
            "horizons": MODEL_CFG["horizons"],
            "aqi_standard": aqi.STANDARD,
            "ready": self.is_ready(),
            "load_error": self.load_error,
        }

    # ── prediction ────────────────────────────────────────────
    def predict_frame(self, X: pd.DataFrame) -> np.ndarray:
        """Predict from an already-built feature frame."""
        if not self.is_ready():
            raise ModelNotReadyError(self.load_error or "no model loaded")

        if self.feature_names:
            missing = [c for c in self.feature_names if c not in X.columns]
            for col in missing:
                X[col] = np.nan
            X = X[self.feature_names]

        preds = self.model.predict(X)
        if hasattr(preds, "to_numpy"):
            preds = preds.to_numpy()
        preds = np.asarray(preds, dtype=float).ravel()
        # Negative pollution is physically impossible.
        return np.clip(preds, 0.0, None)

    def predict(
        self,
        requests: list[dict],
        feature_provider,
    ) -> list[dict]:
        """Predict for a list of {city_id, horizon} requests.

        `feature_provider` supplies the latest feature row per city.
        Injected rather than imported so tests can pass a stub.
        """
        if not self.is_ready():
            raise ModelNotReadyError(self.load_error or "no model loaded")

        city_ids = sorted({r["city_id"] for r in requests})
        features = feature_provider(city_ids)

        if features is None or features.empty:
            raise ValueError(
                "No recent features available for the requested cities. "
                "Has the hourly ingestion job run?"
            )

        rows, meta = [], []
        for req in requests:
            cid, h = req["city_id"], req["horizon"]
            match = features[features["city_id"] == cid]
            if match.empty:
                meta.append({"city_id": cid, "horizon": h, "missing": True})
                continue
            row = match.iloc[[-1]].copy()
            row["horizon"] = h
            rows.append(row)
            meta.append(
                {
                    "city_id": cid,
                    "horizon": h,
                    "missing": False,
                    "base_time": row["timestamp"].iloc[0],
                }
            )

        results: list[dict] = []
        preds = self.predict_frame(pd.concat(rows, ignore_index=True)) if rows else []

        pi = 0
        for m in meta:
            if m["missing"]:
                results.append(
                    {
                        "city_id": m["city_id"],
                        "horizon": m["horizon"],
                        "pm2_5_pred": None,
                        "error": "no recent data for this city",
                    }
                )
                continue

            value = float(preds[pi])
            pi += 1
            base_time = pd.Timestamp(m["base_time"])
            valid_time = base_time + timedelta(hours=m["horizon"])

            results.append(
                {
                    "city_id": m["city_id"],
                    "horizon": m["horizon"],
                    "pm2_5_pred": round(value, 2),
                    "unit": MODEL_CFG["target_unit"],
                    "base_time": base_time.isoformat(),
                    "valid_time": valid_time.isoformat(),
                    "generated_at": datetime.now(UTC).isoformat(),
                    "model_version": self.version,
                    # Provenance matters: this is a model output, not a
                    # sensor reading. The UI must be able to say so.
                    "source": "model_prediction",
                    **aqi.describe(value),
                }
            )

        return results


__all__ = ["ModelLoader", "ModelNotReadyError"]
