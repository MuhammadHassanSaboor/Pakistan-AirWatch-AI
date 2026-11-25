"""Baseline models — owned by IFRAZ.

Run these FIRST, before anybody trains a gradient-boosted model.
Nothing else in the project means anything until these numbers exist:
"MAE = 12" is meaningless; "MAE = 12 versus persistence at 18.9" is a
result.

Models here
-----------
persistence     : tomorrow equals the last observed value
seasonal_naive  : the same hour yesterday
rolling_mean    : the mean of the last 24 hours
ridge           : linear regression with L2 regularisation
decision_tree   : a single shallow tree

Run
---
    python -m src.models.train_baselines --all
    python -m src.models.train_baselines --model ridge --alpha 10
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any

import mlflow
import numpy as np
from sklearn.dummy import DummyRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor

from src.config import MODEL_CFG
from src.features.splits import chrono_split
from src.models.evaluate import (
    BASELINES,
    check_quality_gate,
    metrics_by_horizon,
    regression_metrics,
    summarise,
)
from src.models.tracking import log_metrics_safe, log_params_safe, start_run
from src.models.train_base import load_feature_table, run_training

log = logging.getLogger(__name__)

MEMBER_DEFAULT = "ifraz"


# ──────────────────────────────────────────────────────────────
# Rule-based baselines (no fitting required)
# ──────────────────────────────────────────────────────────────
def run_rule_baseline(method: str) -> dict[str, float]:
    """Evaluate a formula-based baseline and log it to MLflow."""
    if method not in BASELINES:
        raise ValueError(f"Unknown baseline '{method}'. Options: {list(BASELINES)}")

    df = load_feature_table()
    _, val, test = chrono_split(df)

    with start_run(f"baseline-{method}", "baseline") as run:
        log_params_safe({"method": method, "trainable": False})

        t0 = time.time()
        val_pred = np.clip(BASELINES[method](val), 0, None)
        test_pred = np.clip(BASELINES[method](test), 0, None)
        elapsed = time.time() - t0

        # The persistence baseline is the reference every model is
        # measured against, so it is the comparison point here too.
        ref_pred = np.clip(BASELINES["persistence"](test), 0, None)
        ref_mae = float(np.mean(np.abs(test["y"].to_numpy() - ref_pred)))

        metrics: dict[str, float] = {}
        metrics.update(regression_metrics(val["y"], val_pred, prefix="val_"))
        metrics.update(regression_metrics(test["y"], test_pred, prefix="test_"))
        metrics.update(metrics_by_horizon(test, test_pred))
        metrics["baseline_mae"] = ref_mae
        metrics["improvement_pct"] = (
            100.0 * (ref_mae - metrics["test_mae"]) / ref_mae if ref_mae else 0.0
        )
        metrics["train_seconds"] = elapsed

        log_metrics_safe(metrics)
        passed, reasons = check_quality_gate(metrics)
        mlflow.set_tag("quality_gate", "pass" if passed else "fail")
        mlflow.set_tag("is_reference_baseline", str(method == "persistence").lower())

        print(summarise(metrics))
        print(f"  Baseline     : {method}")
        print(f"  MLflow run   : {run.info.run_id}")
        return metrics


# ──────────────────────────────────────────────────────────────
# Trainable baselines
# ──────────────────────────────────────────────────────────────
def build_ridge(params: dict[str, Any]):
    """Linear model. Needs imputation + scaling; trees do not."""
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=params.get("alpha", 1.0), random_state=None)),
        ]
    )


def build_tree(params: dict[str, Any]):
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            (
                "model",
                DecisionTreeRegressor(
                    max_depth=params.get("max_depth", 12),
                    min_samples_leaf=params.get("min_samples_leaf", 50),
                    random_state=MODEL_CFG["random_seed"],
                ),
            ),
        ]
    )


def build_mean(params: dict[str, Any]):
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("model", DummyRegressor(strategy="mean")),
        ]
    )


TRAINABLE = {
    "ridge": (build_ridge, {"alpha": 1.0}),
    "decision_tree": (build_tree, {"max_depth": 12, "min_samples_leaf": 50}),
    "global_mean": (build_mean, {}),
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Train baseline models (Ifraz)")
    ap.add_argument(
        "--model",
        choices=[*BASELINES.keys(), *TRAINABLE.keys()],
        help="which baseline to run",
    )
    ap.add_argument("--all", action="store_true", help="run every baseline")
    ap.add_argument("--alpha", type=float, default=1.0, help="ridge alpha")
    ap.add_argument("--max-depth", type=int, default=12)
    ap.add_argument("--sample-frac", type=float)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.all:
        for method in BASELINES:
            log.info("=== rule baseline: %s ===", method)
            run_rule_baseline(method)
        for name, (factory, defaults) in TRAINABLE.items():
            log.info("=== trainable baseline: %s ===", name)
            run_training(
                model_family=name,
                build_model=factory,
                params=defaults,
                run_name=f"baseline-{name}",
                sample_frac=args.sample_frac,
                register=False,  # baselines are never deployment candidates
            )
        return

    if not args.model:
        ap.error("pass --model NAME or --all")

    if args.model in BASELINES:
        run_rule_baseline(args.model)
    else:
        factory, defaults = TRAINABLE[args.model]
        params = {**defaults}
        if args.model == "ridge":
            params["alpha"] = args.alpha
        if args.model == "decision_tree":
            params["max_depth"] = args.max_depth
        run_training(
            model_family=args.model,
            build_model=factory,
            params=params,
            run_name=f"baseline-{args.model}-{args.alpha if args.model == 'ridge' else args.max_depth}",
            sample_frac=args.sample_frac,
            register=False,
        )


if __name__ == "__main__":
    main()
