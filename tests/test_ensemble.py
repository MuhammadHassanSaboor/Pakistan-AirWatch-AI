"""Tests for the residual / blend models and candidate selection (Mudassar)."""

from __future__ import annotations

import json

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from src.features.splits import chrono_split
from src.models.ensemble import BlendRegressor, ResidualRegressor, anchor_values
from src.models.evaluate import persistence_prediction
from src.models.select_model import load_candidates, select


@pytest.fixture(scope="module")
def splits(sample_features, split_dates_for_sample):
    train_end, val_end = split_dates_for_sample
    return chrono_split(sample_features, train_end, val_end)


def _small_lgb():
    return lgb.LGBMRegressor(
        objective="regression_l1",
        n_estimators=80,
        num_leaves=15,
        learning_rate=0.1,
        verbose=-1,
        random_state=42,
    )


def _small_xgb():
    return xgb.XGBRegressor(
        objective="reg:absoluteerror",
        n_estimators=80,
        max_depth=4,
        learning_rate=0.1,
        random_state=42,
    )


@pytest.fixture(scope="module")
def residual_model(splits, feature_names):
    train, val, _ = splits
    return ResidualRegressor(_small_lgb()).fit(
        train[feature_names], train["y"], eval_set=[(val[feature_names], val["y"])]
    )


@pytest.fixture(scope="module")
def blend_model(splits, feature_names):
    train, val, _ = splits
    blend = BlendRegressor(
        [
            ("lgb", ResidualRegressor(_small_lgb())),
            ("xgb", ResidualRegressor(_small_xgb())),
        ]
    )
    return blend.fit(
        train[feature_names], train["y"], eval_set=[(val[feature_names], val["y"])]
    )


# ── unit ──────────────────────────────────────────────────────────


def test_anchor_falls_back_when_current_value_missing():
    X = pd.DataFrame(
        {
            "pm2_5": [10.0, np.nan, np.nan],
            "pm2_5_lag_1h": [9.0, 20.0, np.nan],
            "pm2_5_roll24_mean": [8.0, 8.0, 30.0],
        }
    )
    np.testing.assert_allclose(anchor_values(X), [10.0, 20.0, 30.0])


def test_anchor_never_returns_nan():
    X = pd.DataFrame({"pm2_5": [np.nan, np.nan]})
    assert np.isfinite(anchor_values(X)).all()


def test_residual_prediction_adds_the_anchor_back():
    class Zero:
        def fit(self, X, y):
            return self

        def predict(self, X):
            return np.zeros(len(X))

        def get_params(self, deep=True):
            return {}

    X = pd.DataFrame({"pm2_5": [5.0, 50.0], "f": [1.0, 2.0]})
    model = ResidualRegressor(Zero()).fit(X, [6.0, 49.0])
    # A zero residual model must reproduce persistence exactly.
    np.testing.assert_allclose(model.predict(X), [5.0, 50.0])


# ── model ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture", ["residual_model", "blend_model"])
def test_output_shape_and_finiteness(request, fixture, splits, feature_names):
    model = request.getfixturevalue(fixture)
    _, _, test = splits
    pred = model.predict(test[feature_names])
    assert pred.shape == (len(test),)
    assert np.isfinite(pred).all()


def test_blend_weights_are_a_convex_combination(blend_model):
    w = blend_model.weights_
    assert len(w) == 2
    assert np.all(w >= 0)
    assert w.sum() == pytest.approx(1.0)


def test_blend_exposes_feature_importances(blend_model, feature_names):
    imp = blend_model.feature_importances_
    assert imp.shape == (len(feature_names),)
    assert np.isfinite(imp).all()


# ── regression: must beat persistence on held-out data ────────────


def test_residual_model_beats_persistence(residual_model, splits, feature_names):
    _, _, test = splits
    model_mae = np.mean(
        np.abs(
            test["y"] - np.clip(residual_model.predict(test[feature_names]), 0, None)
        )
    )
    base_mae = np.mean(np.abs(test["y"] - persistence_prediction(test)))
    assert model_mae < base_mae


# ── integration: pickled model reloads exactly as the API loads it ─


def test_blend_survives_joblib_round_trip(blend_model, splits, feature_names, tmp_path):
    _, _, test = splits
    path = tmp_path / "model.pkl"
    joblib.dump(blend_model, path)
    reloaded = joblib.load(path)
    np.testing.assert_allclose(
        reloaded.predict(test[feature_names]), blend_model.predict(test[feature_names])
    )


# ── candidate selection ──────────────────────────────────────────


def _write(tmp_path, name, **metrics):
    (tmp_path / name).write_text(json.dumps(metrics), encoding="utf-8")


def test_selection_picks_lowest_mae_that_passed_the_gate(tmp_path):
    _write(
        tmp_path,
        "train_metrics.json",
        model_family="xgboost",
        run_name="a",
        test_mae=8.0,
        mae_h24=10.0,
        quality_gate_passed=True,
    )
    _write(
        tmp_path,
        "train_metrics_blend.json",
        model_family="blend",
        run_name="b",
        test_mae=7.0,
        mae_h24=9.0,
        quality_gate_passed=True,
    )
    _write(
        tmp_path,
        "train_metrics_bad.json",
        model_family="x",
        run_name="c",
        test_mae=1.0,
        mae_h24=1.0,
        quality_gate_passed=False,
    )

    result = select(load_candidates(tmp_path))
    assert result["selected_run"] == "b"
    assert result["n_passed_gate"] == 2
    assert result["ranking"][0]["run_name"] == "c"  # ranked, but not eligible


def test_selection_returns_none_when_nothing_passes(tmp_path):
    _write(
        tmp_path,
        "train_metrics.json",
        run_name="a",
        test_mae=99.0,
        quality_gate_passed=False,
    )
    assert select(load_candidates(tmp_path))["selected_run"] is None
