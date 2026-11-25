"""BentoML serving path.

Flask remains the primary API — the course specification requires it
and the rubric grades it. BentoML is demonstrated as the *alternative*
packaging and serving route, which is what §12.2 asks for.

What BentoML adds over Flask, concretely:

* **Versioned serving artifacts.** A "Bento" bundles the model, the
  preprocessing code and the dependency list into one addressable
  version, so `airwatch_bento:abc123` is reproducible without a
  separate Dockerfile.
* **Adaptive batching.** Concurrent single-city requests are merged
  into one model call automatically. For a map refresh touching 134
  cities this matters.
* **One-command containerisation.** `bentoml containerize` generates
  and builds the image.

Usage
-----
    # 1. save the trained model into the BentoML store
    python -m src.serving.bentoml_service --save

    # 2. serve it
    bentoml serve src/serving/bentoml_service.py:svc --port 3000

    # 3. call it
    curl -X POST http://localhost:3000/predict \\
      -H "Content-Type: application/json" \\
      -d '{"cities": [{"city_id": "lahore", "horizon": 24}]}'

    # 4. build and containerise
    bentoml build
    bentoml containerize airwatch_bento:latest
"""

from __future__ import annotations

import argparse
import logging

from src.config import MODEL_CFG, PROJECT_ROOT, settings

log = logging.getLogger(__name__)

MODEL_TAG = "pm25_forecaster"
SERVICE_NAME = "airwatch_bento"


# ──────────────────────────────────────────────────────────────
# Saving the model into the BentoML store
# ──────────────────────────────────────────────────────────────
def save_model_to_bentoml() -> str:
    """Import the production model into BentoML's model store.

    Reads the same artifact the Flask API serves, so both paths are
    demonstrably running the identical model rather than two models
    that happen to share a name.
    """
    import bentoml
    import joblib

    model_dir = PROJECT_ROOT / settings.local_model_path
    model_path = model_dir / "model.pkl"
    if not model_path.exists():
        raise FileNotFoundError(
            f"No model at {model_path}. Run:\n"
            "  python -m src.models.registry export-production"
        )

    model = joblib.load(model_path)

    metadata = {}
    meta_file = model_dir / "metadata.json"
    if meta_file.exists():
        import json

        metadata = json.loads(meta_file.read_text(encoding="utf-8"))

    feature_names = metadata.get("feature_names", [])

    saved = bentoml.sklearn.save_model(
        MODEL_TAG,
        model,
        signatures={"predict": {"batchable": True, "batch_dim": 0}},
        metadata={
            "target": MODEL_CFG["target"],
            "target_unit": MODEL_CFG["target_unit"],
            "horizons": MODEL_CFG["horizons"],
            "n_features": len(feature_names),
            "test_mae": metadata.get("metrics", {}).get("test_mae"),
            "source_run": metadata.get("run_id", "unknown"),
        },
        custom_objects={"feature_names": feature_names},
    )
    log.info("Saved to the BentoML store as %s", saved.tag)
    return str(saved.tag)


# ──────────────────────────────────────────────────────────────
# The service
# ──────────────────────────────────────────────────────────────
def _build_service():
    """Construct the service lazily.

    Importing this module must not fail when no Bento has been saved
    yet — `--save` has to be runnable first, and the test suite imports
    the module to check it is syntactically sound.
    """
    import bentoml
    from bentoml.io import JSON

    try:
        model_ref = bentoml.sklearn.get(f"{MODEL_TAG}:latest")
    except Exception as exc:  # model not saved yet
        log.warning(
            "No '%s' in the BentoML store (%s). "
            "Run: python -m src.serving.bentoml_service --save",
            MODEL_TAG,
            exc,
        )
        return None

    runner = model_ref.to_runner()
    service = bentoml.Service(SERVICE_NAME, runners=[runner])
    feature_names = model_ref.custom_objects.get("feature_names", [])

    @service.api(input=JSON(), output=JSON(), route="/healthz")
    def healthz(_payload: dict) -> dict:
        return {
            "status": "healthy",
            "service": SERVICE_NAME,
            "model": str(model_ref.tag),
            "serving": "bentoml",
        }

    @service.api(input=JSON(), output=JSON(), route="/model-info")
    def model_info(_payload: dict) -> dict:
        return {
            "model_tag": str(model_ref.tag),
            "n_features": len(feature_names),
            "target": MODEL_CFG["target"],
            "target_unit": MODEL_CFG["target_unit"],
            "horizons": MODEL_CFG["horizons"],
            "metadata": dict(model_ref.info.metadata),
            "serving": "bentoml",
        }

    @service.api(input=JSON(), output=JSON(), route="/predict")
    async def predict(payload: dict) -> dict:
        """Predict for a list of {city_id, horizon}.

        Mirrors the Flask contract so the two paths are interchangeable
        from a client's point of view.
        """
        import numpy as np
        import pandas as pd

        from src.serving import aqi
        from src.serving.live_features import get_store
        from src.serving.schemas import validate_predict_request

        check = validate_predict_request(payload)
        if not check.ok:
            return {"error": "validation_failed", "details": check.errors[:20]}

        store = get_store()
        city_ids = sorted({r["city_id"] for r in check.cleaned})
        features = store.latest_features(city_ids)

        if features is None or features.empty:
            return {"error": "no_data", "message": "No recent upstream data."}

        rows, meta = [], []
        for req in check.cleaned:
            match = features[features["city_id"] == req["city_id"]]
            if match.empty:
                meta.append({**req, "missing": True})
                continue
            row = match.iloc[[-1]].copy()
            row["horizon"] = req["horizon"]
            rows.append(row)
            meta.append(
                {**req, "missing": False, "base_time": row["timestamp"].iloc[0]}
            )

        results = []
        if rows:
            frame = pd.concat(rows, ignore_index=True)
            if feature_names:
                for col in feature_names:
                    if col not in frame.columns:
                        frame[col] = np.nan
                frame = frame[feature_names]
            preds = np.clip(
                np.asarray(await runner.predict.async_run(frame), dtype=float), 0, None
            )
        else:
            preds = []

        index = 0
        for item in meta:
            if item["missing"]:
                results.append(
                    {
                        "city_id": item["city_id"],
                        "horizon": item["horizon"],
                        "pm2_5_pred": None,
                        "error": "no recent data for this city",
                    }
                )
                continue
            value = float(preds[index])
            index += 1
            base = pd.Timestamp(item["base_time"])
            results.append(
                {
                    "city_id": item["city_id"],
                    "horizon": item["horizon"],
                    "pm2_5_pred": round(value, 2),
                    "unit": MODEL_CFG["target_unit"],
                    "base_time": base.isoformat(),
                    "valid_time": (
                        base + pd.Timedelta(hours=item["horizon"])
                    ).isoformat(),
                    "source": "model_prediction",
                    "serving": "bentoml",
                    **aqi.describe(value),
                }
            )

        return {
            "model_tag": str(model_ref.tag),
            "count": len(results),
            "predictions": results,
            "attribution": "Source data (c) Open-Meteo.com (CC BY 4.0)",
            "disclaimer": (
                "Academic prototype. Not an official public-health " "warning system."
            ),
        }

    return service


# `bentoml serve ...:svc` imports this module and looks for `svc`.
svc = _build_service()


def main() -> None:
    parser = argparse.ArgumentParser(description="BentoML serving utilities")
    parser.add_argument(
        "--save", action="store_true", help="import the production model"
    )
    parser.add_argument("--list", action="store_true", help="list saved models")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    if args.save:
        tag = save_model_to_bentoml()
        print(f"\nSaved: {tag}")
        print("\nNext:")
        print("  bentoml serve src/serving/bentoml_service.py:svc --port 3000")
        print("  bentoml build")
        print("  bentoml containerize airwatch_bento:latest")
    elif args.list:
        import bentoml

        for model in bentoml.models.list():
            print(f"  {model.tag}  {model.creation_time}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
