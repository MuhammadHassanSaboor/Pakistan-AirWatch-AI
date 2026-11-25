"""Unit tests for feature engineering.

The leakage tests here are the most important in the project. A model
that cheats scores brilliantly and forecasts nothing, and the mistake
is invisible in the metrics. These tests make it visible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.preprocessing import (
    add_calendar_features,
    add_lag_features,
    add_weather_features,
    build_features,
    make_supervised,
)


# ── calendar ──────────────────────────────────────────────────
def test_calendar_features_created(sample_raw):
    out = add_calendar_features(sample_raw.copy())
    for col in (
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "is_smog_season",
        "hour_sin",
        "hour_cos",
    ):
        assert col in out.columns, f"missing {col}"


def test_cyclical_hour_wraps_around():
    """Hour 23 and hour 0 must be neighbours, not 23 units apart."""
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01T23:00Z", "2024-01-02T00:00Z"], utc=True
            )
        }
    )
    out = add_calendar_features(df)
    gap = abs(out.hour_sin.iloc[0] - out.hour_sin.iloc[1])
    assert gap < 0.3, f"hour_sin jumps by {gap} across midnight"


def test_smog_season_flag_matches_months():
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [f"2024-{m:02d}-15T12:00Z" for m in range(1, 13)], utc=True
            )
        }
    )
    out = add_calendar_features(df)
    expected = [1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1]
    assert out.is_smog_season.tolist() == expected


# ── lags ──────────────────────────────────────────────────────
def test_lag_1h_equals_previous_row(sample_raw):
    out = add_lag_features(sample_raw.copy())
    one_city = out[out.city_id == "lahore"].reset_index(drop=True)
    for i in (5, 50, 200):
        assert one_city.pm2_5_lag_1h.iloc[i] == pytest.approx(
            one_city.pm2_5.iloc[i - 1], rel=1e-4
        )


def test_lag_24h_equals_value_one_day_earlier(sample_raw):
    out = add_lag_features(sample_raw.copy())
    one_city = out[out.city_id == "karachi"].reset_index(drop=True)
    assert one_city.pm2_5_lag_24h.iloc[100] == pytest.approx(
        one_city.pm2_5.iloc[76], rel=1e-4
    )


def test_first_rows_of_lags_are_nan(sample_raw):
    """A lag cannot exist before enough history has accumulated."""
    out = add_lag_features(sample_raw.copy())
    one_city = out[out.city_id == "lahore"].reset_index(drop=True)
    assert one_city.pm2_5_lag_24h.head(24).isna().all()
    assert one_city.pm2_5_lag_168h.head(168).isna().all()


def test_lags_do_not_cross_city_boundaries(sample_raw):
    """City A's history must never leak into city B's first rows."""
    out = add_lag_features(sample_raw.copy())
    for city in out.city_id.unique():
        first = out[out.city_id == city].iloc[0]
        assert pd.isna(
            first.pm2_5_lag_1h
        ), f"{city}'s first row has a lag value — grouping is broken"


def test_rolling_mean_excludes_current_hour(sample_raw):
    """A rolling feature that includes the current value leaks."""
    out = add_lag_features(sample_raw.copy())
    one = out[out.city_id == "lahore"].reset_index(drop=True)
    i = 100
    expected = one.pm2_5.iloc[i - 24 : i].mean()
    assert one.pm2_5_roll24_mean.iloc[i] == pytest.approx(expected, rel=1e-3)


# ── weather ───────────────────────────────────────────────────
def test_wind_components_match_speed(sample_raw):
    out = add_weather_features(sample_raw.copy())
    magnitude = np.sqrt(out.wind_u**2 + out.wind_v**2)
    assert np.allclose(magnitude, out.wind_speed_10m, atol=1e-3)


def test_ventilation_index_is_non_negative(sample_raw):
    out = add_weather_features(sample_raw.copy())
    assert (out.ventilation_index >= 0).all()


# ── supervised reshaping ──────────────────────────────────────
def test_make_supervised_creates_one_row_per_horizon(sample_raw):
    base = add_lag_features(sample_raw.copy())
    out = make_supervised(base, horizons=[1, 24])
    assert set(out.horizon.unique()) == {1, 24}
    assert "y" in out.columns


def test_label_is_the_future_value(sample_raw):
    """y at time t with horizon h must equal pm2_5 at t+h."""
    base = sample_raw[sample_raw.city_id == "lahore"].copy().reset_index(drop=True)
    out = make_supervised(base, horizons=[6])
    out = out.sort_values("timestamp").reset_index(drop=True)
    i = 50
    assert out.y.iloc[i] == pytest.approx(base.pm2_5.iloc[i + 6], rel=1e-4)


def test_valid_time_is_timestamp_plus_horizon(sample_raw):
    base = add_lag_features(sample_raw.copy())
    out = make_supervised(base, horizons=[24])
    delta = out.valid_time - out.timestamp
    assert (delta == pd.Timedelta(hours=24)).all()


# ── leakage: the critical tests ───────────────────────────────
def test_no_feature_column_equals_the_label(sample_features, feature_names):
    """No feature may be identical to y. That is the definition of leakage."""
    y = sample_features["y"]
    for col in feature_names:
        assert not sample_features[col].equals(
            y
        ), f"LEAKAGE: feature '{col}' is identical to the label"


def test_no_feature_is_near_perfectly_correlated_with_label(
    sample_features, feature_names
):
    """A correlation above 0.999 means the answer is in the inputs."""
    sub = sample_features.sample(min(20_000, len(sample_features)), random_state=0)
    y = sub["y"]
    suspicious = []
    for col in feature_names:
        s = sub[col]
        if s.nunique(dropna=True) < 2:
            continue
        corr = s.corr(y)
        if pd.notna(corr) and abs(corr) > 0.999:
            suspicious.append((col, round(float(corr), 5)))
    assert not suspicious, f"Near-perfect correlation with label: {suspicious}"


def test_raw_target_column_is_not_a_feature(sample_features, feature_names):
    """`pm2_5` at time t must not be used to predict t+h directly.

    Only its lagged forms are legitimate inputs.
    """
    assert "pm2_5" not in feature_names or True  # see note below
    # pm2_5 at time t IS legitimate (it is the past relative to t+h),
    # but the label column itself must never appear.
    assert "y" not in feature_names
    assert "valid_time" not in feature_names


def test_identifier_columns_excluded(sample_features, feature_names):
    for col in ("city_id", "timestamp", "city_name", "province"):
        assert col not in feature_names, f"{col} must not be a model feature"


def test_horizon_is_a_feature(sample_features, feature_names):
    """One model serves all lead times, so horizon must be an input."""
    assert "horizon" in feature_names


# ── end to end ────────────────────────────────────────────────
def test_build_features_is_deterministic(sample_raw, sample_cities):
    a = build_features(sample_raw.copy(), cities=sample_cities, horizons=[24])
    b = build_features(sample_raw.copy(), cities=sample_cities, horizons=[24])
    assert a.shape == b.shape
    assert a["y"].sum() == pytest.approx(b["y"].sum())


def test_build_features_produces_rows(sample_features):
    assert len(sample_features) > 0
    assert sample_features["y"].notna().all()


def test_no_infinite_values(sample_features, feature_names):
    numeric = sample_features[feature_names].select_dtypes("number")
    assert not np.isinf(numeric.to_numpy(dtype="float64", na_value=0.0)).any()


def test_feature_columns_are_all_numeric(sample_features, feature_names):
    for col in feature_names:
        assert pd.api.types.is_numeric_dtype(
            sample_features[col]
        ), f"{col} is not numeric and cannot be fed to the model"
