"""Tests for the serving internals: model loading and the live cache.

No network, no MLflow, no real model file except ones built in tmp_path.

The degradation tests matter: a prediction service that crashes when a
model is missing tells a monitoring system nothing, whereas one that
starts and reports *why* it is unhealthy can be diagnosed remotely.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta

import joblib
import numpy as np
import pandas as pd
import pytest

from src.config import settings as real_settings
from src.serving import live_features as lf
from src.serving import model_loader as ml
from src.serving.model_loader import ModelLoader, ModelNotReadyError


def _point_settings_at(monkeypatch, model_dir) -> None:
    """Redirect the loader's settings at a temporary model directory.

    `Settings` is a frozen dataclass, so its fields cannot be patched in
    place. Replacing the whole object is both possible and more honest:
    the loader really does read a single immutable settings instance.
    """
    patched = dataclasses.replace(
        real_settings, model_source="local", local_model_path=str(model_dir)
    )
    monkeypatch.setattr(ml, "settings", patched)


class _ConstantModel:
    """Predicts a fixed value; lets us assert on plumbing, not accuracy."""

    def __init__(self, value: float = 42.0):
        self.value = value
        self.seen_columns: list[str] | None = None

    def predict(self, X):
        self.seen_columns = list(X.columns)
        return np.full(len(X), self.value)


@pytest.fixture
def saved_model(tmp_path):
    """A model.pkl plus metadata, exactly as registry export writes it."""
    model_dir = tmp_path / "production"
    model_dir.mkdir()
    joblib.dump(_ConstantModel(55.0), model_dir / "model.pkl")
    (model_dir / "metadata.json").write_text(
        json.dumps(
            {
                "version": "7",
                "stage": "Production",
                "run_id": "abc123",
                "model_family": "xgboost",
                "metrics": {"test_mae": 8.25, "test_r2": 0.80},
                "feature_names": ["f1", "f2", "f3"],
                "exported_at": "2026-11-25T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return model_dir


# ──────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────
def test_loads_a_model_from_disk(monkeypatch, saved_model):
    _point_settings_at(monkeypatch, saved_model)
    loader = ModelLoader(auto_load=False)
    loader.source = "local"
    assert loader.load() is True
    assert loader.is_ready()
    assert loader.version == "7"
    assert loader.algorithm == "xgboost"
    assert loader.feature_names == ["f1", "f2", "f3"]
    assert loader.metrics["test_mae"] == 8.25


def test_missing_model_degrades_instead_of_crashing(monkeypatch, tmp_path):
    """The service must still start so /health can report the reason."""
    _point_settings_at(monkeypatch, tmp_path / "void")
    loader = ModelLoader(auto_load=False)
    loader.source = "local"
    assert loader.load() is False
    assert not loader.is_ready()
    assert "FileNotFoundError" in loader.load_error


def test_info_reports_the_load_error(monkeypatch, tmp_path):
    _point_settings_at(monkeypatch, tmp_path / "void")
    loader = ModelLoader(auto_load=False)
    loader.source = "local"
    loader.load()
    info = loader.info()
    assert info["ready"] is False
    assert info["load_error"]


def test_info_contains_the_contract_fields(monkeypatch, saved_model):
    _point_settings_at(monkeypatch, saved_model)
    loader = ModelLoader(auto_load=False)
    loader.source = "local"
    loader.load()
    info = loader.info()
    for key in (
        "model_name",
        "model_version",
        "stage",
        "algorithm",
        "horizons",
        "target",
        "target_unit",
        "aqi_standard",
        "ready",
    ):
        assert key in info


def test_model_without_metadata_still_loads(tmp_path, monkeypatch):
    bare = tmp_path / "bare"
    bare.mkdir()
    joblib.dump(_ConstantModel(), bare / "model.pkl")

    _point_settings_at(monkeypatch, bare)
    loader = ModelLoader(auto_load=False)
    loader.source = "local"
    assert loader.load() is True
    assert loader.version == "local"


# ──────────────────────────────────────────────────────────────
# Prediction plumbing
# ──────────────────────────────────────────────────────────────
def test_predict_frame_raises_when_no_model_loaded():
    loader = ModelLoader(auto_load=False)
    with pytest.raises(ModelNotReadyError):
        loader.predict_frame(pd.DataFrame({"a": [1]}))


def test_predict_frame_reorders_columns_to_training_order():
    """Tree models index features positionally — order silently matters."""
    model = _ConstantModel()
    loader = ModelLoader(auto_load=False)
    loader.model = model
    loader.feature_names = ["f1", "f2", "f3"]

    loader.predict_frame(pd.DataFrame({"f3": [1], "f1": [2], "f2": [3]}))
    assert model.seen_columns == ["f1", "f2", "f3"]


def test_predict_frame_fills_missing_features_with_nan():
    model = _ConstantModel()
    loader = ModelLoader(auto_load=False)
    loader.model = model
    loader.feature_names = ["f1", "f2", "f3"]

    loader.predict_frame(pd.DataFrame({"f1": [1.0]}))
    assert model.seen_columns == ["f1", "f2", "f3"]


def test_predict_frame_clips_negative_predictions():
    loader = ModelLoader(auto_load=False)
    loader.model = _ConstantModel(-50.0)
    loader.feature_names = []
    out = loader.predict_frame(pd.DataFrame({"a": [1, 2, 3]}))
    assert (out >= 0).all(), "a negative concentration is physically impossible"


def test_predict_builds_a_complete_response():
    loader = ModelLoader(auto_load=False)
    loader.model = _ConstantModel(80.0)
    loader.feature_names = []
    loader.version = "7"

    features = pd.DataFrame(
        {
            "city_id": ["lahore"],
            "timestamp": pd.to_datetime(["2026-11-25T03:00:00Z"]),
            "f1": [1.0],
        }
    )
    results = loader.predict(
        [{"city_id": "lahore", "horizon": 24}],
        feature_provider=lambda ids: features[features.city_id.isin(ids)],
    )
    item = results[0]
    assert item["pm2_5_pred"] == 80.0
    assert item["source"] == "model_prediction"
    assert item["model_version"] == "7"
    assert item["aqi_category"] == "Unhealthy"
    assert item["valid_time"] > item["base_time"]


def test_predict_reports_a_city_with_no_recent_data():
    loader = ModelLoader(auto_load=False)
    loader.model = _ConstantModel()
    loader.feature_names = []

    features = pd.DataFrame(
        {
            "city_id": ["lahore"],
            "timestamp": pd.to_datetime(["2026-11-25T03:00:00Z"]),
            "f1": [1.0],
        }
    )
    results = loader.predict(
        [{"city_id": "lahore", "horizon": 1}, {"city_id": "skardu", "horizon": 1}],
        feature_provider=lambda _ids: features,
    )
    by_city = {r["city_id"]: r for r in results}
    assert by_city["lahore"]["pm2_5_pred"] is not None
    assert by_city["skardu"]["pm2_5_pred"] is None
    assert "error" in by_city["skardu"]


def test_predict_raises_when_the_provider_returns_nothing():
    """An empty provider means the ingestion job has not run."""
    loader = ModelLoader(auto_load=False)
    loader.model = _ConstantModel()
    loader.feature_names = []
    with pytest.raises(ValueError, match="No recent features"):
        loader.predict(
            [{"city_id": "lahore", "horizon": 1}],
            feature_provider=lambda _ids: pd.DataFrame(),
        )


def test_predict_uses_the_newest_row_per_city():
    loader = ModelLoader(auto_load=False)
    loader.model = _ConstantModel()
    loader.feature_names = []

    features = pd.DataFrame(
        {
            "city_id": ["lahore", "lahore"],
            "timestamp": pd.to_datetime(
                ["2026-11-25T01:00:00Z", "2026-11-25T03:00:00Z"]
            ),
            "f1": [1.0, 2.0],
        }
    )
    result = loader.predict(
        [{"city_id": "lahore", "horizon": 1}], feature_provider=lambda _i: features
    )[0]
    assert result["base_time"].startswith("2026-11-25T03:00")


# ──────────────────────────────────────────────────────────────
# Live feature cache
# ──────────────────────────────────────────────────────────────
def _stamps(hours: int):
    """Half past, half future — exactly what the live endpoint returns."""
    now = pd.Timestamp.now(tz="UTC").floor("h")
    return pd.date_range(
        now - timedelta(hours=hours // 2), periods=hours, freq="h", tz="UTC"
    )


def _stub_aq_blocks(n_cities: int, hours: int = 72):
    """Air-quality blocks: pollutants only."""
    stamps = _stamps(hours)
    rng = np.random.default_rng(0)
    return [
        pd.DataFrame(
            {
                "timestamp": stamps,
                "pm2_5": rng.gamma(4, 12, hours),
                "pm10": rng.gamma(5, 20, hours),
                "ozone": rng.uniform(10, 90, hours),
                "nitrogen_dioxide": rng.uniform(2, 60, hours),
            }
        )
        for _ in range(n_cities)
    ]


def _stub_wx_blocks(n_cities: int, hours: int = 72):
    """Weather blocks: meteorology only.

    The two endpoints MUST return disjoint columns. If they overlap,
    `aq.merge(wx, on="timestamp")` suffixes the duplicates to _x/_y and
    `pm2_5` silently vanishes — which is a real failure mode worth
    reproducing faithfully in the stub.
    """
    stamps = _stamps(hours)
    rng = np.random.default_rng(1)
    return [
        pd.DataFrame(
            {
                "timestamp": stamps,
                "temperature_2m": rng.normal(22, 4, hours),
                "relative_humidity_2m": rng.uniform(20, 90, hours),
                "wind_speed_10m": rng.gamma(2, 2, hours),
                "wind_direction_10m": rng.uniform(0, 360, hours),
                "boundary_layer_height": rng.uniform(100, 2000, hours),
                "precipitation": np.zeros(hours),
                "surface_pressure": rng.uniform(990, 1020, hours),
                "cloud_cover": rng.uniform(0, 100, hours),
            }
        )
        for _ in range(n_cities)
    ]


@pytest.fixture
def stubbed_store(monkeypatch, sample_cities):
    """A LiveFeatureStore with the network replaced by synthetic data."""
    monkeypatch.setattr(lf, "load_cities", lambda: sample_cities)
    monkeypatch.setattr(
        lf, "fetch_air_quality_live", lambda lats, lons, **k: _stub_aq_blocks(len(lats))
    )
    monkeypatch.setattr(
        lf, "fetch_weather_forecast", lambda lats, lons, **k: _stub_wx_blocks(len(lats))
    )
    return lf.LiveFeatureStore()


def test_store_starts_stale(stubbed_store):
    assert stubbed_store.is_stale
    assert stubbed_store.age_seconds is None


def test_refresh_populates_the_cache(stubbed_store):
    stubbed_store.refresh()
    assert not stubbed_store.is_stale
    status = stubbed_store.status()
    assert status["cached"] is True
    assert status["rows"] > 0


def test_latest_features_returns_one_row_per_city(stubbed_store, sample_cities):
    latest = stubbed_store.latest_features()
    assert len(latest) <= len(sample_cities)
    assert latest["city_id"].is_unique


def test_latest_features_excludes_future_rows(stubbed_store):
    """The live endpoint returns forecast hours too; predicting from a
    row that has not happened yet would be meaningless."""
    latest = stubbed_store.latest_features()
    assert (latest["timestamp"] <= pd.Timestamp.now(tz="UTC")).all()


def test_latest_features_filters_by_city(stubbed_store):
    subset = stubbed_store.latest_features(["lahore"])
    assert set(subset["city_id"]) <= {"lahore"}


def test_latest_features_include_engineered_columns(stubbed_store):
    latest = stubbed_store.latest_features()
    for column in ("pm2_5_lag_1h", "hour_sin", "ventilation_index", "is_smog_season"):
        assert column in latest.columns, f"serving must produce {column}"


def test_provider_forecast_is_strictly_future(stubbed_store):
    """Our prediction and the provider's forecast must stay separable."""
    forecast = stubbed_store.provider_forecast("lahore")
    if not forecast.empty:
        assert (forecast["timestamp"] > pd.Timestamp.now(tz="UTC")).all()


def test_recent_observations_respects_the_window(stubbed_store):
    observed = stubbed_store.recent_observations("lahore", days=1)
    if not observed.empty:
        cutoff = pd.Timestamp.now(tz="UTC") - timedelta(days=1)
        assert (observed["timestamp"] >= cutoff).all()


def test_cache_is_reused_within_its_ttl(monkeypatch, sample_cities):
    calls = {"n": 0}

    def counting_fetch(lats, _lons, **_k):
        calls["n"] += 1
        return _stub_aq_blocks(len(lats))

    monkeypatch.setattr(lf, "load_cities", lambda: sample_cities)
    monkeypatch.setattr(lf, "fetch_air_quality_live", counting_fetch)
    monkeypatch.setattr(
        lf, "fetch_weather_forecast", lambda lats, lons, **k: _stub_wx_blocks(len(lats))
    )

    store = lf.LiveFeatureStore()
    store.latest_features()
    first = calls["n"]
    store.latest_features()
    assert calls["n"] == first, "a second call within the TTL must not refetch"


def test_get_store_is_a_singleton():
    assert lf.get_store() is lf.get_store()
