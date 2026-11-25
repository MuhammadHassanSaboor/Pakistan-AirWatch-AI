"""Integration tests: the stages must work together, not just alone."""

from __future__ import annotations

import json
from itertools import pairwise

import joblib
import numpy as np
import pandas as pd
import pytest

from src.config import DATA_CFG, MODEL_CFG, feature_exclusions, split_dates
from src.data.validation import validate_raw
from src.features.preprocessing import build_features, feature_columns
from src.features.splits import chrono_split
from src.models.evaluate import evaluate_model
from src.serving import aqi


def test_raw_to_prediction_end_to_end(
    sample_raw, sample_cities, split_dates_for_sample, tmp_path
):
    """validate -> features -> split -> train -> save -> load -> predict."""
    import lightgbm as lgb

    # 1. validate
    ok, report = validate_raw(sample_raw)
    assert "overall_status" in report

    # 2. features
    features = build_features(sample_raw.copy(), cities=sample_cities, horizons=[1, 24])
    assert len(features) > 0
    cols = feature_columns(features)
    assert len(cols) > 20

    # 3. split
    train_end, val_end = split_dates_for_sample
    train, val, test = chrono_split(features, train_end, val_end)

    # 4. train
    model = lgb.LGBMRegressor(
        n_estimators=40, num_leaves=15, verbose=-1, random_state=42
    )
    model.fit(train[cols], train["y"])

    # 5. evaluate
    metrics, preds = evaluate_model(model, val, test, cols)
    assert metrics["test_mae"] > 0
    assert len(preds) == len(test)

    # 6. serialise and reload
    path = tmp_path / "model.pkl"
    joblib.dump(model, path)
    reloaded = joblib.load(path)

    # 7. the reloaded model must predict identically
    a = model.predict(test[cols].head(50))
    b = reloaded.predict(test[cols].head(50))
    assert np.allclose(a, b)


def test_serving_features_match_training_features(
    sample_raw, sample_cities, feature_names
):
    """Training-serving skew check.

    The live path applies the same transformation functions as the
    training path, so the resulting feature set must match. If this
    fails, the model receives different inputs in production than it
    was trained on — the single most dangerous bug in an ML system.
    """
    from src.features.preprocessing import (
        add_calendar_features,
        add_lag_features,
        add_spatial_features,
        add_static_features,
        add_weather_features,
    )

    # Mirror LiveFeatureStore._build_features exactly.
    live = sample_raw.copy()
    live = live.merge(
        sample_cities[["city_id", "city_name", "province", "population"]],
        on="city_id",
        how="left",
    )
    live = add_calendar_features(live)
    live = add_lag_features(live)
    live = add_weather_features(live)
    live = add_spatial_features(live)
    live = add_static_features(live)
    live["horizon"] = 24

    missing = [c for c in feature_names if c not in live.columns]
    assert (
        not missing
    ), f"Serving path cannot produce these training features: {missing}"


def test_model_loader_predicts_from_live_shaped_frame(
    trained_model, feature_names, sample_features
):
    """ModelLoader must accept a frame built by the live path."""
    from src.serving.model_loader import ModelLoader

    loader = ModelLoader(auto_load=False)
    loader.model = trained_model
    loader.feature_names = feature_names
    loader.version = "test"

    latest = (
        sample_features.sort_values("timestamp")
        .groupby("city_id", as_index=False)
        .tail(1)
    )

    results = loader.predict(
        [{"city_id": "lahore", "horizon": 24}],
        feature_provider=lambda ids: latest[latest.city_id.isin(ids)],
    )
    assert len(results) == 1
    assert results[0]["pm2_5_pred"] >= 0
    assert results[0]["source"] == "model_prediction"


def test_model_loader_reorders_columns_to_training_order(
    trained_model, feature_names, sample_features
):
    """Column order must not change the prediction.

    Tree models index features positionally; if the serving frame
    arrives in a different order the predictions are silently wrong.
    """
    from src.serving.model_loader import ModelLoader

    loader = ModelLoader(auto_load=False)
    loader.model = trained_model
    loader.feature_names = feature_names

    frame = sample_features.head(20).copy()
    expected = loader.predict_frame(frame.copy())

    shuffled = frame[list(reversed(frame.columns.tolist()))]
    actual = loader.predict_frame(shuffled)

    assert np.allclose(expected, actual)


def test_model_loader_fills_missing_features_with_nan(
    trained_model, feature_names, sample_features
):
    """A missing upstream variable must not crash serving."""
    from src.serving.model_loader import ModelLoader

    loader = ModelLoader(auto_load=False)
    loader.model = trained_model
    loader.feature_names = feature_names

    frame = sample_features.head(10).drop(columns=[feature_names[0]])
    preds = loader.predict_frame(frame)
    assert len(preds) == 10
    assert np.isfinite(preds).all()


def test_predictions_are_clipped_to_non_negative(
    trained_model, feature_names, sample_features
):
    from src.serving.model_loader import ModelLoader

    loader = ModelLoader(auto_load=False)
    loader.model = trained_model
    loader.feature_names = feature_names
    preds = loader.predict_frame(sample_features.head(200).copy())
    assert (preds >= 0).all()


# ── configuration consistency ─────────────────────────────────
def test_split_dates_are_ordered():
    train_end, val_end = split_dates()
    assert pd.Timestamp(train_end) < pd.Timestamp(val_end)


def test_split_dates_fall_inside_the_configured_data_range():
    """Catches the classic error of copying split dates between projects."""
    start = pd.Timestamp(DATA_CFG["time"]["air_quality_start"], tz="UTC")
    train_end, val_end = split_dates()
    assert pd.Timestamp(train_end) > start
    assert pd.Timestamp(val_end) > pd.Timestamp(train_end)


def test_label_and_identifiers_are_excluded_from_features():
    excl = feature_exclusions()
    for col in ("y", "timestamp", "city_id"):
        assert col in excl


def test_quality_gate_thresholds_are_sane():
    gate = MODEL_CFG["quality_gate"]
    assert 0 < gate["max_test_mae"] < 500
    assert 0 < gate["min_improvement_over_baseline_pct"] < 100


def test_horizons_match_between_config_and_schemas():
    from src.serving.schemas import VALID_HORIZONS

    assert VALID_HORIZONS == set(MODEL_CFG["horizons"])


# ── AQI conversion ────────────────────────────────────────────
@pytest.mark.parametrize(
    "pm25,expected_category",
    [
        (5.0, "Good"),
        (20.0, "Moderate"),
        (45.0, "Unhealthy for Sensitive Groups"),
        (100.0, "Unhealthy"),
        (180.0, "Very Unhealthy"),
        (300.0, "Hazardous"),
    ],
)
def test_aqi_categories(pm25, expected_category):
    assert aqi.describe(pm25)["aqi_category"] == expected_category


def test_aqi_is_monotonic():
    """Higher pollution must never produce a lower index."""
    values = [0, 5, 10, 20, 40, 60, 100, 150, 200, 300, 400]
    indices = [aqi.pm25_to_aqi(v) for v in values]
    assert indices == sorted(indices)


def test_aqi_handles_missing_and_invalid():
    assert aqi.pm25_to_aqi(None) is None
    assert aqi.pm25_to_aqi(float("nan")) is None
    assert aqi.pm25_to_aqi(-1) is None


def test_aqi_caps_at_500():
    assert aqi.pm25_to_aqi(99_999) == 500


def test_aqi_legend_covers_full_scale():
    bands = aqi.legend()
    assert bands[0]["aqi_lower"] == 0
    assert bands[-1]["aqi_upper"] == 500
    for a, b in pairwise(bands):
        assert b["aqi_lower"] == a["aqi_upper"] + 1


# ── artifact contracts ────────────────────────────────────────
def test_candidate_metadata_is_json_serialisable(tmp_path):
    """train_base writes this file; serving reads it. Keep them in sync."""
    meta = {
        "run_name": "x",
        "model_family": "xgboost",
        "metrics": {"test_mae": 12.3},
        "feature_names": ["a", "b"],
        "quality_gate_passed": True,
    }
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["metrics"]["test_mae"] == 12.3
    assert loaded["feature_names"] == ["a", "b"]
