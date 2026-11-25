"""XGBoost — owned by HASSAN.

Gradient-boosted trees are the strongest general-purpose model for
tabular time series and are the most likely winner of our three-way
comparison.

Run
---
    python -m src.models.train_xgboost
    python -m src.models.train_xgboost --max-depth 10 --lr 0.03
    python -m src.models.train_xgboost --sweep        # many configs
"""

from __future__ import annotations

import argparse
import logging
from itertools import product
from typing import Any

import xgboost as xgb

from src.config import MODEL_CFG
from src.models.train_base import run_training

log = logging.getLogger(__name__)

DEFAULTS = dict(MODEL_CFG["xgboost"])


def build_xgboost(params: dict[str, Any]) -> xgb.XGBRegressor:
    """XGBoost regressor.

    `reg:absoluteerror` optimises MAE directly, which is our headline
    metric. Squared error would chase the extreme smog spikes at the
    expense of everyday accuracy.

    Trees handle NaN natively, so no imputation step is needed — and
    that matters here, because the lag features are genuinely missing
    at the start of each city's series.
    """
    cfg = {**DEFAULTS, **params}
    return xgb.XGBRegressor(**cfg)


def _run_one(params: dict[str, Any], sample_frac: float | None) -> dict:
    name = (
        f"xgboost-d{params.get('max_depth')}"
        f"-lr{params.get('learning_rate')}"
        f"-n{params.get('n_estimators')}"
    )
    return run_training(
        model_family="xgboost",
        build_model=build_xgboost,
        params=params,
        run_name=name,
        supports_eval_set=True,  # enables early stopping on the val set
        sample_frac=sample_frac,
    )


def sweep(sample_frac: float | None = None) -> None:
    """Hyperparameter sweep. Every config lands in the same experiment."""
    depths = [4, 6, 8, 10]
    lrs = [0.03, 0.05, 0.1]
    estimators = [400, 800]

    combos = list(product(depths, lrs, estimators))
    log.info("Sweeping %d configurations", len(combos))

    for i, (d, lr, n) in enumerate(combos, start=1):
        log.info("[%d/%d] depth=%s lr=%s n=%s", i, len(combos), d, lr, n)
        params = {
            **DEFAULTS,
            "max_depth": d,
            "learning_rate": lr,
            "n_estimators": n,
        }
        try:
            _run_one(params, sample_frac)
        except Exception as exc:
            log.error("Config failed (d=%s lr=%s n=%s): %s", d, lr, n, exc)


def main() -> None:
    ap = argparse.ArgumentParser(description="Train XGBoost (Hassan)")
    ap.add_argument("--max-depth", type=int, default=DEFAULTS["max_depth"])
    ap.add_argument("--lr", type=float, default=DEFAULTS["learning_rate"])
    ap.add_argument("--n-estimators", type=int, default=DEFAULTS["n_estimators"])
    ap.add_argument("--subsample", type=float, default=DEFAULTS["subsample"])
    ap.add_argument("--colsample", type=float, default=DEFAULTS["colsample_bytree"])
    ap.add_argument(
        "--min-child-weight", type=int, default=DEFAULTS["min_child_weight"]
    )
    ap.add_argument("--sweep", action="store_true", help="run a full sweep")
    ap.add_argument(
        "--sample-frac", type=float, help="train on a fraction of rows (fast iteration)"
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.sweep:
        sweep(args.sample_frac)
        return

    params = {
        **DEFAULTS,
        "max_depth": args.max_depth,
        "learning_rate": args.lr,
        "n_estimators": args.n_estimators,
        "subsample": args.subsample,
        "colsample_bytree": args.colsample,
        "min_child_weight": args.min_child_weight,
    }
    _run_one(params, args.sample_frac)


if __name__ == "__main__":
    main()
