"""Shared pytest fixtures.

Fixtures build synthetic data rather than reading the real dataset so
that the whole suite runs in CI with no network, no DVC pull and no
MLflow server. Tests must be fast and hermetic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

RNG = np.random.default_rng(42)


def _synthetic_city(
    city_id: str,
    lat: float,
    lon: float,
    elevation: int,
    n_hours: int,
    start: str = "2024-01-01",
    base_pm25: float = 60.0,
) -> pd.DataFrame:
    """One city's hourly series with a realistic daily + seasonal shape."""
    ts = pd.date_range(start, periods=n_hours, freq="h", tz="UTC")
    hour = ts.hour.to_numpy()
    doy = ts.dayofyear.to_numpy()

    # Daily cycle: morning and evening traffic peaks.
    daily = 18 * np.sin(2 * np.pi * (hour - 6) / 24)
    # Seasonal cycle: winter smog.
    seasonal = 45 * np.cos(2 * np.pi * (doy - 15) / 365.25)
    noise = RNG.normal(0, 8, n_hours)
    pm25 = np.clip(base_pm25 + daily + seasonal + noise, 1, None)

    return pd.DataFrame(
        {
            "city_id": city_id,
            "timestamp": ts,
            "pm2_5": pm25.astype("float32"),
            "pm10": (pm25 * RNG.uniform(1.4, 2.2, n_hours)).astype("float32"),
            "carbon_monoxide": RNG.uniform(200, 1500, n_hours).astype("float32"),
            "nitrogen_dioxide": RNG.uniform(5, 90, n_hours).astype("float32"),
            "sulphur_dioxide": RNG.uniform(1, 40, n_hours).astype("float32"),
            "ozone": RNG.uniform(10, 120, n_hours).astype("float32"),
            "dust": RNG.uniform(0, 300, n_hours).astype("float32"),
            "temperature_2m": (
                22
                + 10 * np.sin(2 * np.pi * (doy - 100) / 365.25)
                + 6 * np.sin(2 * np.pi * (hour - 9) / 24)
                + RNG.normal(0, 1.5, n_hours)
            ).astype("float32"),
            "relative_humidity_2m": RNG.uniform(20, 95, n_hours).astype("float32"),
            "dew_point_2m": RNG.uniform(0, 25, n_hours).astype("float32"),
            "apparent_temperature": RNG.uniform(5, 45, n_hours).astype("float32"),
            "precipitation": (RNG.random(n_hours) < 0.05)
            * RNG.uniform(0, 8, n_hours).astype("float32"),
            "surface_pressure": RNG.uniform(960, 1030, n_hours).astype("float32"),
            "cloud_cover": RNG.uniform(0, 100, n_hours).astype("float32"),
            "wind_speed_10m": RNG.gamma(2.0, 2.0, n_hours).astype("float32"),
            "wind_direction_10m": RNG.uniform(0, 360, n_hours).astype("float32"),
            "wind_gusts_10m": RNG.gamma(2.5, 3.0, n_hours).astype("float32"),
            "boundary_layer_height": RNG.uniform(80, 2200, n_hours).astype("float32"),
            "shortwave_radiation": np.clip(
                600 * np.sin(np.pi * (hour - 6) / 12), 0, None
            ).astype("float32"),
            "latitude": np.float32(lat),
            "longitude": np.float32(lon),
            "elevation_m": np.float32(elevation),
            "data_source": "synthetic",
        }
    )


@pytest.fixture(scope="session")
def sample_cities() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "city_id": "lahore",
                "city_name": "Lahore",
                "province": "Punjab",
                "latitude": 31.5204,
                "longitude": 74.3587,
                "population": 11_126_285,
                "elevation_m": 217,
            },
            {
                "city_id": "karachi",
                "city_name": "Karachi",
                "province": "Sindh",
                "latitude": 24.8607,
                "longitude": 67.0011,
                "population": 14_910_352,
                "elevation_m": 10,
            },
            {
                "city_id": "peshawar",
                "city_name": "Peshawar",
                "province": "Khyber Pakhtunkhwa",
                "latitude": 34.0151,
                "longitude": 71.5249,
                "population": 1_970_042,
                "elevation_m": 331,
            },
            {
                "city_id": "quetta",
                "city_name": "Quetta",
                "province": "Balochistan",
                "latitude": 30.1798,
                "longitude": 66.9750,
                "population": 1_001_205,
                "elevation_m": 1680,
            },
        ]
    )


@pytest.fixture(scope="session")
def sample_raw(sample_cities) -> pd.DataFrame:
    """~3 months of hourly data for four cities."""
    n_hours = 24 * 90
    frames = [
        _synthetic_city(
            c.city_id,
            c.latitude,
            c.longitude,
            c.elevation_m,
            n_hours,
            base_pm25=40 + 15 * i,
        )
        for i, c in enumerate(sample_cities.itertuples(index=False))
    ]
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["city_id", "timestamp"])
        .reset_index(drop=True)
    )


@pytest.fixture(scope="session")
def sample_features(sample_raw, sample_cities) -> pd.DataFrame:
    from src.features.preprocessing import build_features

    return build_features(sample_raw.copy(), cities=sample_cities, horizons=[1, 24])


@pytest.fixture(scope="session")
def feature_names(sample_features) -> list[str]:
    from src.features.preprocessing import feature_columns

    return feature_columns(sample_features)


@pytest.fixture(scope="session")
def split_dates_for_sample(sample_features) -> tuple[str, str]:
    """Split dates derived from the synthetic range, not the config."""
    ts = pd.to_datetime(sample_features["timestamp"], utc=True)
    lo, hi = ts.min(), ts.max()
    span = hi - lo
    return (
        (lo + span * 0.6).isoformat(),
        (lo + span * 0.8).isoformat(),
    )


@pytest.fixture(scope="session")
def trained_model(sample_features, feature_names, split_dates_for_sample):
    """A small, fast LightGBM trained on the synthetic data."""
    import lightgbm as lgb

    from src.features.splits import chrono_split

    train_end, val_end = split_dates_for_sample
    train, val, _ = chrono_split(sample_features, train_end, val_end)

    model = lgb.LGBMRegressor(
        objective="regression_l1",
        n_estimators=60,
        num_leaves=15,
        learning_rate=0.15,
        verbose=-1,
        random_state=42,
    )
    model.fit(train[feature_names], train["y"])
    return model


@pytest.fixture(scope="session")
def test_split(sample_features, split_dates_for_sample):
    from src.features.splits import chrono_split

    train_end, val_end = split_dates_for_sample
    _, _, test = chrono_split(sample_features, train_end, val_end)
    return test


@pytest.fixture
def api_client(monkeypatch, sample_features, trained_model, feature_names):
    """Flask test client with the model and live store stubbed out.

    No network, no MLflow, no real model file — so API tests run
    anywhere, including a clean CI container.
    """
    from src.serving import model_loader as ml_mod

    class StubLoader(ml_mod.ModelLoader):
        def __init__(self):
            super().__init__(auto_load=False)
            self.model = trained_model
            self.feature_names = feature_names
            self.version = "test-1"
            self.stage = "Production"
            self.run_id = "testrun"
            self.algorithm = "lightgbm"
            self.source = "local"
            self.metrics = {"test_mae": 9.9}
            self.loaded_at = "2026-01-01T00:00:00+00:00"

    latest = (
        sample_features.sort_values("timestamp")
        .groupby("city_id", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )

    class StubStore:
        def latest_features(self, city_ids=None):
            df = latest
            if city_ids:
                df = df[df["city_id"].isin(city_ids)]
            return df.reset_index(drop=True)

        def recent_observations(self, city_id, days=7):
            return sample_features[sample_features.city_id == city_id].tail(48)

        def provider_forecast(self, city_id):
            return sample_features[sample_features.city_id == city_id].tail(6)

        def status(self):
            return {"cached": True, "stale": False, "rows": len(latest)}

        @property
        def age_seconds(self):
            return 10.0

    monkeypatch.setattr(ml_mod, "ModelLoader", StubLoader)

    import src.serving.app as app_mod

    monkeypatch.setattr(app_mod, "ModelLoader", StubLoader)
    monkeypatch.setattr(app_mod, "get_store", lambda: StubStore())

    application = app_mod.create_app()
    application.config["TESTING"] = True
    with application.test_client() as client:
        yield client
