"""Shared evaluation metrics and the deployment quality gate.

**All three team members import from this module.** Metric names are
frozen in `configs/model_params.yaml`. If one person computes "MAE"
and another "mean_abs_err", the MLflow comparison silently breaks.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.config import MODEL_CFG, quality_gate

log = logging.getLogger(__name__)

TARGET = MODEL_CFG["target"]


def regression_metrics(y_true, y_pred, prefix: str = "") -> dict[str, float]:
    """MAE / RMSE / R2 with a consistent naming prefix."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    y_true, y_pred = y_true[mask], y_pred[mask]

    if len(y_true) == 0:
        return {
            f"{prefix}mae": float("nan"),
            f"{prefix}rmse": float("nan"),
            f"{prefix}r2": float("nan"),
        }

    return {
        f"{prefix}mae": float(mean_absolute_error(y_true, y_pred)),
        f"{prefix}rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        f"{prefix}r2": float(r2_score(y_true, y_pred)),
    }


def metrics_by_horizon(
    df: pd.DataFrame, y_pred, horizons: list[int] | None = None
) -> dict[str, float]:
    """MAE per forecast lead time.

    Always report this. A persistence baseline looks excellent at +1h
    and terrible at +24h; a single averaged number hides that, and an
    examiner will ask.
    """
    horizons = horizons or list(MODEL_CFG["horizons"])
    preds = np.asarray(y_pred, dtype=float)
    out: dict[str, float] = {}
    for h in horizons:
        mask = (df["horizon"] == h).to_numpy()
        if mask.sum() == 0:
            continue
        out[f"mae_h{h}"] = float(mean_absolute_error(df.loc[mask, "y"], preds[mask]))
    return out


def metrics_by_group(
    df: pd.DataFrame, y_pred, group_col: str, top_n: int = 10
) -> pd.DataFrame:
    """Error broken down by province, month, city, etc."""
    tmp = df[[group_col, "y"]].copy()
    tmp["pred"] = np.asarray(y_pred, dtype=float)
    tmp["abs_err"] = (tmp["y"] - tmp["pred"]).abs()
    agg = (
        tmp.groupby(group_col)
        .agg(mae=("abs_err", "mean"), n=("abs_err", "size"), mean_actual=("y", "mean"))
        .sort_values("mae", ascending=False)
    )
    return agg.head(top_n).round(3)


# ──────────────────────────────────────────────────────────────
# Baselines
# ──────────────────────────────────────────────────────────────
def persistence_prediction(df: pd.DataFrame, target: str = TARGET) -> np.ndarray:
    """Carry the most recent observed value forward.

    The honest benchmark every model must beat. If a gradient-boosted
    model cannot beat this, something is wrong with the model, not the
    problem.
    """
    col = f"{target}_lag_1h"
    if col not in df.columns:
        raise KeyError(f"{col} required for the persistence baseline")
    fallback = f"{target}_roll24_mean"
    pred = df[col]
    if fallback in df.columns:
        pred = pred.fillna(df[fallback])
    return pred.fillna(pred.median()).to_numpy(dtype=float)


def seasonal_naive_prediction(df: pd.DataFrame, target: str = TARGET) -> np.ndarray:
    """Predict the same hour yesterday — captures the daily cycle."""
    col = f"{target}_lag_24h"
    if col not in df.columns:
        return persistence_prediction(df, target)
    pred = df[col].fillna(df.get(f"{target}_lag_1h", df[col]))
    return pred.fillna(pred.median()).to_numpy(dtype=float)


def rolling_mean_prediction(df: pd.DataFrame, target: str = TARGET) -> np.ndarray:
    col = f"{target}_roll24_mean"
    if col not in df.columns:
        return persistence_prediction(df, target)
    pred = df[col]
    return pred.fillna(pred.median()).to_numpy(dtype=float)


BASELINES = {
    "persistence": persistence_prediction,
    "seasonal_naive": seasonal_naive_prediction,
    "rolling_mean": rolling_mean_prediction,
}


# ──────────────────────────────────────────────────────────────
# Full evaluation
# ──────────────────────────────────────────────────────────────
def evaluate_model(
    model: Any,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: list[str],
    baseline: str = "persistence",
) -> tuple[dict[str, float], np.ndarray]:
    """Compute every frozen metric for one model.

    Returns (metrics, test_predictions).
    """
    val_pred = model.predict(val_df[feature_cols])
    test_pred = model.predict(test_df[feature_cols])

    # Negative pollution is physically impossible.
    val_pred = np.clip(val_pred, 0, None)
    test_pred = np.clip(test_pred, 0, None)

    base_pred = BASELINES[baseline](test_df)
    base_mae = float(mean_absolute_error(test_df["y"], base_pred))

    metrics: dict[str, float] = {}
    metrics.update(regression_metrics(val_df["y"], val_pred, prefix="val_"))
    metrics.update(regression_metrics(test_df["y"], test_pred, prefix="test_"))
    metrics.update(metrics_by_horizon(test_df, test_pred))

    metrics["baseline_mae"] = base_mae
    metrics["improvement_pct"] = (
        100.0 * (base_mae - metrics["test_mae"]) / base_mae if base_mae > 0 else 0.0
    )

    return metrics, test_pred


def check_quality_gate(
    metrics: dict[str, float], production_mae: float | None = None
) -> tuple[bool, list[str]]:
    """Decide whether a model may be deployed.

    Returns (passed, reasons). A model failing ANY rule must not reach
    production — enforced in CI, the Airflow DAG and the Kubeflow
    pipeline so the rule cannot be bypassed by accident.
    """
    gate = quality_gate()
    reasons: list[str] = []

    test_mae = metrics.get("test_mae", float("inf"))
    if test_mae > gate["max_test_mae"]:
        reasons.append(
            f"test_mae {test_mae:.2f} exceeds the limit "
            f"{gate['max_test_mae']:.2f} ug/m3"
        )

    improvement = metrics.get("improvement_pct", -float("inf"))
    if improvement < gate["min_improvement_over_baseline_pct"]:
        reasons.append(
            f"improvement over baseline {improvement:.1f}% is below the "
            f"required {gate['min_improvement_over_baseline_pct']:.1f}%"
        )

    if production_mae is not None and production_mae > 0:
        rel = 100.0 * (production_mae - test_mae) / production_mae
        if rel < gate["min_improvement_over_production_pct"]:
            reasons.append(
                f"candidate is only {rel:+.1f}% better than the deployed "
                f"model (needs {gate['min_improvement_over_production_pct']:.1f}%)"
            )

    passed = not reasons
    if passed:
        log.info("Quality gate PASSED (test_mae=%.2f, +%.1f%%)", test_mae, improvement)
    else:
        for r in reasons:
            log.error("Quality gate FAILED: %s", r)
    return passed, reasons


def summarise(metrics: dict[str, float]) -> str:
    """Human-readable block printed at the end of every training run.

    Deliberately ASCII-only. Box-drawing characters raise
    UnicodeEncodeError on a default Windows console (cp1252), and this
    text is also written to Docker logs, CI output and Airflow task
    logs, none of which are guaranteed to be UTF-8.
    """
    lines = [
        "",
        "  +-- Evaluation ------------------------------",
        f"  |  test MAE   : {metrics.get('test_mae', float('nan')):8.3f} ug/m3",
        f"  |  test RMSE  : {metrics.get('test_rmse', float('nan')):8.3f} ug/m3",
        f"  |  test R2    : {metrics.get('test_r2', float('nan')):8.3f}",
        f"  |  val  MAE   : {metrics.get('val_mae', float('nan')):8.3f} ug/m3",
        "  |",
        f"  |  baseline   : {metrics.get('baseline_mae', float('nan')):8.3f} ug/m3",
        f"  |  improvement: {metrics.get('improvement_pct', float('nan')):8.1f} %",
        "  |",
    ]
    for h in MODEL_CFG["horizons"]:
        key = f"mae_h{h}"
        if key in metrics:
            lines.append(f"  |  MAE @ +{h:>2}h  : {metrics[key]:8.3f} ug/m3")
    lines.append("  +--------------------------------------------")
    return "\n".join(lines)


__all__ = [
    "regression_metrics",
    "metrics_by_horizon",
    "metrics_by_group",
    "BASELINES",
    "persistence_prediction",
    "seasonal_naive_prediction",
    "rolling_mean_prediction",
    "evaluate_model",
    "check_quality_gate",
    "summarise",
]
