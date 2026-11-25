"""Shared training harness.

Every member's training script calls `run_training()` with their own
model factory. The data loading, splitting, evaluation, MLflow logging
and artifact generation are therefore IDENTICAL across all three
members — which is exactly what makes the comparison table valid.

A member only writes:
    * which estimator to build
    * which hyperparameters to vary
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import joblib
import mlflow
import numpy as np
import pandas as pd

from src.config import DATA_CFG, MODEL_CFG, PROJECT_ROOT, resolve, settings
from src.features.preprocessing import feature_columns
from src.features.splits import chrono_split, describe_splits
from src.models import plots
from src.models.evaluate import (
    check_quality_gate,
    evaluate_model,
    metrics_by_group,
    summarise,
)
from src.models.tracking import (
    log_artifact_if_exists,
    log_metrics_safe,
    log_params_safe,
    start_run,
    verify_required_metrics,
)

log = logging.getLogger(__name__)


class Estimator(Protocol):
    def fit(self, X, y, **kwargs) -> Any: ...
    def predict(self, X) -> np.ndarray: ...


ModelFactory = Callable[[dict[str, Any]], Estimator]


def load_feature_table(path: str | Path | None = None) -> pd.DataFrame:
    p = resolve(path or DATA_CFG["paths"]["processed"])
    if not p.exists():
        raise FileNotFoundError(
            f"Feature table not found: {p}\n"
            "Run:  python -m src.features.build_features\n"
            "(or:  dvc repro features)"
        )
    log.info("Loading %s", p)
    df = pd.read_parquet(p)
    log.info("Loaded %d rows x %d columns", len(df), df.shape[1])
    return df


def run_training(
    *,
    model_family: str,
    build_model: ModelFactory,
    params: dict[str, Any],
    run_name: str | None = None,
    data_path: str | Path | None = None,
    supports_eval_set: bool = False,
    register: bool = True,
    sample_frac: float | None = None,
    save_local: bool = True,
) -> dict[str, float]:
    """Train one model, evaluate it and log everything to MLflow."""
    data_path = data_path or DATA_CFG["paths"]["processed"]
    df = load_feature_table(data_path)

    if sample_frac and 0 < sample_frac < 1:
        df = df.sample(frac=sample_frac, random_state=MODEL_CFG["random_seed"])
        df = df.sort_values(["city_id", "timestamp"]).reset_index(drop=True)
        log.info("Sampled %.0f%% -> %d rows", sample_frac * 100, len(df))

    train, val, test = chrono_split(df)
    feats = feature_columns(df)
    log.info("Training on %d features", len(feats))

    run_name = run_name or f"{model_family}-{int(time.time())}"

    with start_run(run_name, model_family, data_path) as run:
        log_params_safe(params)
        log_params_safe(
            {
                "n_features": len(feats),
                "n_train_rows": len(train),
                "n_val_rows": len(val),
                "n_test_rows": len(test),
                "n_cities": int(df.city_id.nunique()),
                "sample_frac": sample_frac or 1.0,
            }
        )
        mlflow.log_dict(describe_splits(train, val, test), "split_summary.json")
        mlflow.log_dict({"feature_names": feats}, "feature_names.json")

        model = build_model(params)

        log.info("Fitting %s ...", model_family)
        t0 = time.time()
        if supports_eval_set:
            model.fit(
                train[feats],
                train["y"],
                eval_set=[(val[feats], val["y"])],
                verbose=False,
            )
        else:
            model.fit(train[feats], train["y"])
        train_seconds = time.time() - t0
        log.info("Fitted in %.1fs", train_seconds)

        metrics, test_pred = evaluate_model(model, val, test, feats)
        metrics["train_seconds"] = train_seconds
        log_metrics_safe(metrics)

        missing = verify_required_metrics(metrics)
        if missing:
            log.warning(
                "Run is missing required metrics %s — it will not be "
                "comparable with other members' runs.",
                missing,
            )

        # ── Error breakdowns (required by the report) ──────────
        reports_dir = PROJECT_ROOT / "reports" / run_name
        reports_dir.mkdir(parents=True, exist_ok=True)

        breakdowns: dict[str, Any] = {}
        if "province" in test.columns:
            by_prov = metrics_by_group(test, test_pred, "province", top_n=20)
            breakdowns["by_province"] = by_prov.to_dict("index")
        test_month = test.assign(month=test["timestamp"].dt.month)
        by_month = metrics_by_group(test_month, test_pred, "month", top_n=12)
        breakdowns["by_month"] = {
            str(k): v for k, v in by_month.to_dict("index").items()
        }
        by_city = metrics_by_group(test, test_pred, "city_id", top_n=15)
        breakdowns["worst_cities"] = by_city.to_dict("index")
        mlflow.log_dict(breakdowns, "error_breakdown.json")

        # ── Plots ─────────────────────────────────────────────
        try:
            plots.residual_plot(
                test["y"],
                test_pred,
                reports_dir / "residuals.png",
                title=f"{model_family} — {run_name}",
            )
            plots.feature_importance_plot(
                model, feats, reports_dir / "feature_importance.png"
            )
            plots.horizon_error_plot(metrics, reports_dir / "horizon_error.png")
            busiest = test.city_id.value_counts().idxmax()
            plots.timeseries_plot(
                test, test_pred, busiest, reports_dir / "timeseries.png"
            )
            for png in reports_dir.glob("*.png"):
                log_artifact_if_exists(png, artifact_path="plots")
        except Exception as exc:
            log.warning("Plot generation failed: %s", exc)

        # ── Quality gate ──────────────────────────────────────
        passed, reasons = check_quality_gate(metrics)
        mlflow.set_tag("quality_gate", "pass" if passed else "fail")
        if reasons:
            mlflow.set_tag("quality_gate_reasons", " | ".join(reasons)[:480])

        # ── Model artifact ────────────────────────────────────
        signature_input = train[feats].head(5)
        try:
            flavour = _mlflow_flavour(model)
            kwargs: dict[str, Any] = {
                "artifact_path": "model",
                "input_example": signature_input,
            }
            # Only register models that passed the gate. A failing model
            # must never become a deployment candidate.
            if register and passed:
                kwargs["registered_model_name"] = MODEL_CFG["registry"]["model_name"]
            flavour(model, **kwargs)
        except Exception as exc:
            log.warning("MLflow model logging failed (%s); saving locally", exc)

        if save_local:
            local_dir = PROJECT_ROOT / "models" / "candidates" / run_name
            local_dir.mkdir(parents=True, exist_ok=True)
            joblib.dump(model, local_dir / "model.pkl")
            (local_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "run_name": run_name,
                        "run_id": run.info.run_id,
                        "model_family": model_family,
                        "member": settings.member,
                        "params": {k: str(v) for k, v in params.items()},
                        "metrics": metrics,
                        "feature_names": feats,
                        "quality_gate_passed": passed,
                        "quality_gate_reasons": reasons,
                        "target": MODEL_CFG["target"],
                        "horizons": MODEL_CFG["horizons"],
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            log.info("Local artifact -> %s", local_dir)

        # DVC reads this file for `dvc metrics show` and `metrics diff`.
        metrics_file = PROJECT_ROOT / "reports" / "train_metrics.json"
        metrics_file.parent.mkdir(parents=True, exist_ok=True)
        metrics_file.write_text(
            json.dumps(
                {
                    **{k: round(float(v), 5) for k, v in metrics.items()},
                    "model_family": model_family,
                    "member": settings.member,
                    "run_name": run_name,
                    "quality_gate_passed": passed,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        print(summarise(metrics))
        print(f"  Quality gate : {'PASS' if passed else 'FAIL'}")
        for r in reasons:
            print(f"    - {r}")
        print(f"  MLflow run   : {run.info.run_id}")
        print(f"  Member       : {settings.member}")

        return metrics


def _mlflow_flavour(model) -> Callable:
    """Pick the right MLflow flavour so the model reloads correctly."""
    mod = type(model).__module__
    if mod.startswith("xgboost"):
        import mlflow.xgboost

        return mlflow.xgboost.log_model
    if mod.startswith("lightgbm"):
        import mlflow.lightgbm

        return mlflow.lightgbm.log_model
    import mlflow.sklearn

    return mlflow.sklearn.log_model


__all__ = ["run_training", "load_feature_table", "ModelFactory"]
