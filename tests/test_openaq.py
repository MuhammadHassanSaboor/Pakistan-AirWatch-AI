"""Tests for OpenAQ ground-truth ingestion.

No network and no API key: every HTTP call is stubbed. These run in CI
and for any teammate who has not obtained a key.

The station-matching and validation tests matter most — OpenAQ is the
only independent check we have on a target that is otherwise a model
product, so a quiet bug here would undermine the project's central
honesty claim rather than just lose a feature.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data import openaq
from src.data.openaq import OpenAQError, _classify, _haversine_km


# ──────────────────────────────────────────────────────────────
# Geography
# ──────────────────────────────────────────────────────────────
def test_haversine_zero_for_identical_points():
    assert _haversine_km(31.5, 74.3, np.array([31.5]), np.array([74.3]))[0] == (
        pytest.approx(0.0, abs=1e-6)
    )


def test_haversine_matches_a_known_distance():
    """Lahore to Karachi is roughly 1,020 km great-circle."""
    d = _haversine_km(31.5204, 74.3587, np.array([24.8607]), np.array([67.0011]))
    assert 990 < d[0] < 1060


def test_haversine_is_vectorised():
    d = _haversine_km(
        31.5, 74.3, np.array([31.5, 24.86, 34.01]), np.array([74.3, 67.0, 71.52])
    )
    assert d.shape == (3,)
    assert d[0] < d[2] < d[1]


# ──────────────────────────────────────────────────────────────
# Station classification
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "name,expected",
    [
        ("US Diplomatic Post: Lahore", "reference"),
        ("US Embassy Islamabad", "reference"),
        ("Consulate Karachi", "reference"),
        ("Soomra Society, Scheme 33", "low_cost"),
        ("Farhan Shah Labs", "low_cost"),
        ("", "low_cost"),
    ],
)
def test_station_tier_classification(name, expected):
    assert _classify(name) == expected


def test_unknown_stations_default_to_low_cost():
    """The safe default: never assume reference grade without evidence."""
    assert _classify("Some New Sensor 42") == "low_cost"


# ──────────────────────────────────────────────────────────────
# City matching
# ──────────────────────────────────────────────────────────────
def _stations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # essentially on top of Lahore
            {
                "location_id": 1,
                "location_name": "US Diplomatic Post: Lahore",
                "latitude": 31.5204,
                "longitude": 74.3587,
                "pm25_sensor_id": 101,
                "provider_tier": "reference",
            },
            # ~8 km from Karachi centre
            {
                "location_id": 2,
                "location_name": "Karachi Community",
                "latitude": 24.93,
                "longitude": 67.03,
                "pm25_sensor_id": 102,
                "provider_tier": "low_cost",
            },
            # middle of the Arabian Sea — matches nothing
            {
                "location_id": 3,
                "location_name": "Offshore Buoy",
                "latitude": 21.0,
                "longitude": 64.0,
                "pm25_sensor_id": 103,
                "provider_tier": "low_cost",
            },
        ]
    )


def test_matching_attaches_the_nearest_city():
    out = openaq.match_to_cities(_stations(), max_km=25)
    by_id = dict(zip(out["location_id"], out["city_id"], strict=False))
    assert by_id[1] == "lahore"
    assert by_id[2] == "karachi"


def test_matching_drops_stations_beyond_the_radius():
    """A station 300 km offshore is not evidence about any city."""
    out = openaq.match_to_cities(_stations(), max_km=25)
    assert 3 not in set(out["location_id"])


def test_matching_records_the_distance():
    out = openaq.match_to_cities(_stations(), max_km=25)
    lahore = out[out.location_id == 1].iloc[0]
    assert lahore["distance_km"] < 1.0


def test_matching_radius_is_honoured():
    tight = openaq.match_to_cities(_stations(), max_km=1)
    assert set(tight["location_id"]) == {1}


def test_matching_handles_no_stations():
    out = openaq.match_to_cities(pd.DataFrame(), max_km=25)
    assert out.empty


# ──────────────────────────────────────────────────────────────
# HTTP behaviour
# ──────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_missing_api_key_raises_a_clear_error(monkeypatch):
    import dataclasses

    from src.config import settings as real

    monkeypatch.setattr(
        openaq, "settings", dataclasses.replace(real, openaq_api_key="")
    )
    with pytest.raises(OpenAQError, match="OPENAQ_API_KEY is not set"):
        openaq._headers()


def test_rejected_key_is_reported_distinctly(monkeypatch):
    monkeypatch.setattr(openaq, "_headers", lambda: {"X-API-Key": "x"})
    monkeypatch.setattr(openaq.requests, "get", lambda *a, **k: _Resp(401, text="no"))
    with pytest.raises(OpenAQError, match="rejected the API key"):
        openaq._get("/locations", {})


def test_rate_limit_is_retried(monkeypatch):
    calls = {"n": 0}

    def fake_get(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(429, text="slow down")
        return _Resp(200, {"results": []})

    monkeypatch.setattr(openaq, "_headers", lambda: {})
    monkeypatch.setattr(openaq.requests, "get", fake_get)
    monkeypatch.setattr(openaq.time, "sleep", lambda _s: None)

    assert openaq._get("/locations", {}) == {"results": []}
    assert calls["n"] == 2


def test_locations_parser_keeps_only_pm25_stations(monkeypatch):
    payload = {
        "results": [
            {
                "id": 1,
                "name": "US Diplomatic Post: Lahore",
                "locality": "Lahore",
                "coordinates": {"latitude": 31.52, "longitude": 74.36},
                "sensors": [{"id": 11, "parameter": {"name": "pm25"}}],
                "provider": {"name": "AirNow"},
            },
            {  # temperature only — not useful as PM2.5 ground truth
                "id": 2,
                "name": "Weather Only",
                "coordinates": {"latitude": 24.9, "longitude": 67.0},
                "sensors": [{"id": 22, "parameter": {"name": "temperature"}}],
            },
            {  # no coordinates — cannot be matched to a city
                "id": 3,
                "name": "No Coords",
                "coordinates": {},
                "sensors": [{"id": 33, "parameter": {"name": "pm25"}}],
            },
        ]
    }
    monkeypatch.setattr(openaq, "_get", lambda *a, **k: payload)

    df = openaq.fetch_locations()
    assert list(df["location_id"]) == [1]
    assert df.iloc[0]["provider_tier"] == "reference"
    assert df.iloc[0]["pm25_sensor_id"] == 11


def test_sensor_hours_filters_impossible_readings(monkeypatch):
    payload = {
        "results": [
            {
                "period": {"datetimeFrom": {"utc": "2026-11-01T00:00:00Z"}},
                "value": 42.0,
            },
            {
                "period": {"datetimeFrom": {"utc": "2026-11-01T01:00:00Z"}},
                "value": -5.0,
            },
            {"period": {"datetimeFrom": {"utc": "2026-11-01T02:00:00Z"}}, "value": 9e9},
            {
                "period": {"datetimeFrom": {"utc": "2026-11-01T03:00:00Z"}},
                "value": None,
            },
        ]
    }
    monkeypatch.setattr(openaq, "_get", lambda *a, **k: payload)
    monkeypatch.setattr(openaq.time, "sleep", lambda _s: None)

    df = openaq.fetch_sensor_hours(101, "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z")
    assert len(df) == 1
    assert df.iloc[0]["pm2_5_observed"] == 42.0


# ──────────────────────────────────────────────────────────────
# Validation against the reanalysis
# ──────────────────────────────────────────────────────────────
def _paired(n=400, offset=0.0, noise=3.0, seed=0):
    rng = np.random.default_rng(seed)
    stamps = pd.date_range("2026-10-01", periods=n, freq="h", tz="UTC")
    observed = rng.gamma(4, 18, n)
    return (
        pd.DataFrame(
            {
                "city_id": "lahore",
                "timestamp": stamps,
                "pm2_5_observed": observed,
                "provider_tier": "reference",
            }
        ),
        pd.DataFrame(
            {
                "city_id": "lahore",
                "timestamp": stamps,
                "pm2_5": observed + offset + rng.normal(0, noise, n),
            }
        ),
    )


def test_validation_reports_bias_and_correlation(monkeypatch, tmp_path):
    obs, ours = _paired(offset=12.0)

    monkeypatch.setattr(openaq.pd, "read_parquet", lambda *a, **k: ours)
    monkeypatch.setattr(openaq, "resolve", lambda p: tmp_path / str(p).split("/")[-1])

    report = openaq.validate_against_reanalysis(observations=obs)
    assert report["status"] == "ok"
    # The reanalysis was constructed to read ~12 ug/m3 high.
    assert 10 < report["overall"]["bias"] < 14
    assert report["overall"]["correlation"] > 0.9
    assert report["overall"]["n"] > 300


def test_validation_detects_no_overlap(monkeypatch, tmp_path):
    obs, ours = _paired()
    ours = ours.assign(timestamp=ours["timestamp"] + pd.Timedelta(days=400))

    monkeypatch.setattr(openaq.pd, "read_parquet", lambda *a, **k: ours)
    monkeypatch.setattr(openaq, "resolve", lambda p: tmp_path / str(p).split("/")[-1])

    report = openaq.validate_against_reanalysis(observations=obs)
    assert report["status"] == "no_overlap"


def test_validation_breaks_results_down_by_tier(monkeypatch, tmp_path):
    obs, ours = _paired(n=300, offset=5.0)
    low = obs.copy()
    low["provider_tier"] = "low_cost"
    low["pm2_5_observed"] = low["pm2_5_observed"] * 1.6  # typical over-read
    combined = pd.concat([obs, low], ignore_index=True)

    monkeypatch.setattr(openaq.pd, "read_parquet", lambda *a, **k: ours)
    monkeypatch.setattr(openaq, "resolve", lambda p: tmp_path / str(p).split("/")[-1])

    report = openaq.validate_against_reanalysis(observations=combined)
    assert set(report["by_tier"]) == {"reference", "low_cost"}
    # Low-cost sensors read higher, so the reanalysis looks lower against them.
    assert (
        report["by_tier"]["low_cost"]["bias"] < report["by_tier"]["reference"]["bias"]
    )
