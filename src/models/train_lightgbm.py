"""LightGBM and RandomForest — owned by MUDASSAR.

LightGBM grows trees leaf-wise rather than level-wise, so it is
typically several times faster than XGBoost on a dataset of this size
and sometimes more accurate. RandomForest is included as a robustness
check: it is a very different algorithm (bagging, not boosting), so if
it lands in the same accuracy range we can trust the result is real
and not an artefact of one library.

Run
---
    python -m src.models.train_lightgbm
    python -m src.models.train_lightgbm --model random_forest
    python -m src.models.train_lightgbm --sweep
"""

from __future__ import annotations

import argparse
import logging
from itertools import product
from typing import Any

import lightgbm as lgb
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from src.config import MODEL_CFG
from src.models.train_base import run_training

log = logging.getLogger(__name__)

LGB_DEFAULTS = dict(MODEL_CFG["lightgbm"])
RF_DEFAULTS = dict(MODEL_CFG["random_forest"])


def build_lightgbm(params: dict[str, Any]) -> lgb.LGBMRegressor:
    """`regression_l1` optimises MAE, matching our headline metric."""
    cfg = {**LGB_DEFAULTS, **params, "verbose": -1}
    return lgb.LGBMRegressor(**cfg)


def build_random_forest(params: dict[str, Any]) -> Pipeline:
    """RandomForest cannot handle NaN, so impute first.

    The imputer lives inside the Pipeline so the identical transform is
    applied at serving time — this is how we avoid training/serving
    skew without extra code.
    """
    cfg = {**RF_DEFAULTS, **params}
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("model", RandomForestRegressor(**cfg)),
        ]
    )


def build_hist_gbr(params: dict[str, Any]) -> HistGradientBoostingRegressor:
    """scikit-learn's own histogram booster — handles NaN natively."""
    return HistGradientBoostingRegressor(
        loss="absolute_error",
        max_depth=params.get("max_depth", 8),
        learning_rate=params.get("learning_rate", 0.05),
        max_iter=params.get("max_iter", 500),
        min_samples_leaf=params.get("min_samples_leaf", 40),
        l2_regularization=params.get("l2_regularization", 1.0),
        random_state=MODEL_CFG["random_seed"],
        early_stopping=True,
        validation_fraction=0.1,
    )


BUILDERS = {
    "lightgbm": (build_lightgbm, LGB_DEFAULTS, False),
    "random_forest": (build_random_forest, RF_DEFAULTS, False),
    "hist_gbr": (
        build_hist_gbr,
        {"max_depth": 8, "learning_rate": 0.05, "max_iter": 500},
        False,
    ),
}


def _run_one(family: str, params: dict[str, Any], sample_frac: float | None) -> dict:
    builder, _, eval_set = BUILDERS[family]
    if family == "lightgbm":
        name = (
            f"lightgbm-leaves{params.get('num_leaves')}"
            f"-lr{params.get('learning_rate')}"
            f"-n{params.get('n_estimators')}"
        )
    elif family == "random_forest":
        name = f"rf-n{params.get('n_estimators')}-d{params.get('max_depth')}"
    else:
        name = f"histgbr-d{params.get('max_depth')}-lr{params.get('learning_rate')}"

    return run_training(
        model_family=family,
        build_model=builder,
        params=params,
        run_name=name,
        supports_eval_set=eval_set,
        sample_frac=sample_frac,
    )


def sweep(sample_frac: float | None = None) -> None:
    """Sweep LightGBM, then a couple of RandomForest configurations."""
    leaves = [31, 64, 127]
    lrs = [0.03, 0.05, 0.1]
    estimators = [400, 800]

    combos = list(product(leaves, lrs, estimators))
    log.info("LightGBM sweep: %d configurations", len(combos))
    for i, (nl, lr, n) in enumerate(combos, start=1):
        log.info("[%d/%d] leaves=%s lr=%s n=%s", i, len(combos), nl, lr, n)
        params = {
            **LGB_DEFAULTS,
            "num_leaves": nl,
            "learning_rate": lr,
            "n_estimators": n,
        }
        try:
            _run_one("lightgbm", params, sample_frac)
        except Exception as exc:
            log.error("LightGBM config failed: %s", exc)

    log.info("RandomForest comparison runs")
    for n, d in [(150, 14), (300, 20)]:
        try:
            _run_one(
                "random_forest",
                {**RF_DEFAULTS, "n_estimators": n, "max_depth": d},
                # RF is memory-hungry; subsample unless told otherwise
                sample_frac or 0.3,
            )
        except Exception as exc:
            log.error("RandomForest config failed: %s", exc)


def main() -> None:
    ap = argparse.ArgumentParser(description="Train LightGBM / RandomForest (Mudassar)")
    ap.add_argument("--model", choices=list(BUILDERS), default="lightgbm")
    ap.add_argument("--num-leaves", type=int, default=LGB_DEFAULTS["num_leaves"])
    ap.add_argument("--lr", type=float, default=LGB_DEFAULTS["learning_rate"])
    ap.add_argument("--n-estimators", type=int, default=LGB_DEFAULTS["n_estimators"])
    ap.add_argument("--max-depth", type=int, default=RF_DEFAULTS["max_depth"])
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--sample-frac", type=float)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.sweep:
        sweep(args.sample_frac)
        return

    if args.model == "lightgbm":
        params = {
            **LGB_DEFAULTS,
            "num_leaves": args.num_leaves,
            "learning_rate": args.lr,
            "n_estimators": args.n_estimators,
        }
    elif args.model == "random_forest":
        params = {
            **RF_DEFAULTS,
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
        }
    else:
        params = {"max_depth": args.max_depth, "learning_rate": args.lr}

    _run_one(args.model, params, args.sample_frac)


if __name__ == "__main__":
    main()
