"""Model wrappers that improve on a single boosted model — owned by MUDASSAR.

Two ideas, both standard in forecasting and both leakage-safe:

1. **Residual target** (``ResidualRegressor``)
   Instead of learning the PM2.5 *level* at ``t+h``, learn the *change*
   from the value observed at ``t``:  ``y - pm2_5(t)``.  Pollution is
   strongly autocorrelated, so the level is mostly "whatever it is
   now"; the change is the hard part, and it is far better centred and
   scaled for trees. The prediction is ``pm2_5(t) + predicted_change``,
   so the model can never do worse than persistence by drifting far
   from the current reading. ``pm2_5(t)`` is known at prediction time.

2. **Validation-weighted blend** (``BlendRegressor``)
   LightGBM (leaf-wise) and XGBoost (level-wise) make different
   errors. A weighted average of the two usually beats either. The
   weight is chosen on the VALIDATION split only — the test split is
   never seen during fitting, so the reported test score stays honest.

Both are scikit-learn compatible (``fit`` / ``predict``), so the shared
harness, MLflow (sklearn flavour), joblib and the Flask API use them
without changes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin, clone

from src.config import MODEL_CFG

log = logging.getLogger(__name__)

TARGET: str = MODEL_CFG["target"]


def anchor_values(X: pd.DataFrame, base_col: str = TARGET) -> np.ndarray:
    """The value observed at time ``t`` — the anchor the residual is relative to.

    Falls back to the 1-hour lag, then the 24-hour rolling mean, so a
    single missing reading never produces a NaN prediction.
    """
    base = X[base_col] if base_col in X.columns else pd.Series(np.nan, index=X.index)
    for fallback in (f"{base_col}_lag_1h", f"{base_col}_roll24_mean"):
        if fallback in X.columns:
            base = base.fillna(X[fallback])
    return base.fillna(0.0).to_numpy(dtype=float)


def _fit_estimator(est, X, y, eval_set=None, early_stopping_rounds: int = 100):
    """Fit any of our boosters, wiring early stopping the way each library wants."""
    if eval_set is None:
        return est.fit(X, y)
    module = type(est).__module__
    if module.startswith("lightgbm"):
        import lightgbm as lgb

        return est.fit(
            X,
            y,
            eval_set=eval_set,
            callbacks=[
                lgb.early_stopping(early_stopping_rounds, verbose=False),
                lgb.log_evaluation(0),
            ],
        )
    if module.startswith("xgboost"):
        return est.fit(X, y, eval_set=eval_set, verbose=False)
    return est.fit(X, y)


class ResidualRegressor(RegressorMixin, BaseEstimator):
    """Learn ``y - anchor`` and add the anchor back at prediction time."""

    def __init__(self, estimator: Any, base_col: str = TARGET):
        self.estimator = estimator
        self.base_col = base_col

    def fit(self, X: pd.DataFrame, y, eval_set=None, **_ignored):
        y = np.asarray(y, dtype=float)
        residual = y - anchor_values(X, self.base_col)
        eval_resid = None
        if eval_set:
            eval_resid = [
                (Xv, np.asarray(yv, dtype=float) - anchor_values(Xv, self.base_col))
                for Xv, yv in eval_set
            ]
        self.estimator_ = clone(self.estimator)
        _fit_estimator(self.estimator_, X, residual, eval_resid)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.estimator_.predict(X) + anchor_values(X, self.base_col)

    @property
    def feature_importances_(self) -> np.ndarray:
        return self.estimator_.feature_importances_


class BlendRegressor(RegressorMixin, BaseEstimator):
    """Weighted average of several regressors, weights tuned on validation.

    ``weight_grid`` is the step for the simplex search. With two members
    this is an exact 1-D search over w in {0, 0.05, ..., 1}.
    """

    def __init__(self, estimators: list[tuple[str, Any]], weight_step: float = 0.05):
        self.estimators = estimators
        self.weight_step = weight_step

    def fit(self, X: pd.DataFrame, y, eval_set=None, **_ignored):
        self.members_: list[tuple[str, Any]] = []
        for name, est in self.estimators:
            log.info("Blend: fitting member %s", name)
            fitted = clone(est)
            if isinstance(fitted, ResidualRegressor):
                fitted.fit(X, y, eval_set=eval_set)
            else:
                _fit_estimator(fitted, X, y, eval_set)
            self.members_.append((name, fitted))

        if eval_set:
            Xv, yv = eval_set[0]
            self.weights_ = self._search_weights(Xv, np.asarray(yv, dtype=float))
        else:
            self.weights_ = np.full(len(self.members_), 1.0 / len(self.members_))
        log.info(
            "Blend weights: %s",
            {
                n: round(float(w), 3)
                for (n, _), w in zip(self.members_, self.weights_, strict=True)
            },
        )
        return self

    def _search_weights(self, Xv: pd.DataFrame, yv: np.ndarray) -> np.ndarray:
        preds = np.column_stack([m.predict(Xv) for _, m in self.members_])
        preds = np.clip(preds, 0, None)
        if preds.shape[1] == 1:
            return np.array([1.0])
        if preds.shape[1] == 2:
            grid = np.arange(0.0, 1.0 + 1e-9, self.weight_step)
            maes = [
                np.mean(np.abs(yv - (w * preds[:, 0] + (1 - w) * preds[:, 1])))
                for w in grid
            ]
            w = float(grid[int(np.argmin(maes))])
            return np.array([w, 1.0 - w])
        # >2 members: coordinate search from equal weights.
        w = np.full(preds.shape[1], 1.0 / preds.shape[1])
        best = np.mean(np.abs(yv - preds @ w))
        for _ in range(20):
            improved = False
            for i in range(len(w)):
                for delta in (self.weight_step, -self.weight_step):
                    cand = w.copy()
                    cand[i] = max(0.0, cand[i] + delta)
                    cand /= cand.sum()
                    mae = np.mean(np.abs(yv - preds @ cand))
                    if mae < best - 1e-6:
                        best, w, improved = mae, cand, True
            if not improved:
                break
        return w

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        preds = np.column_stack([m.predict(X) for _, m in self.members_])
        return preds @ self.weights_

    @property
    def feature_importances_(self) -> np.ndarray:
        imps = []
        for (_, m), w in zip(self.members_, self.weights_, strict=True):
            imp = np.asarray(m.feature_importances_, dtype=float)
            total = imp.sum()
            imps.append(w * (imp / total if total > 0 else imp))
        return np.sum(imps, axis=0)


__all__ = ["BlendRegressor", "ResidualRegressor", "anchor_values"]
