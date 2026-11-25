"""Tests for the Open-Meteo client and the ingestion helpers.

No network access. Every HTTP interaction is stubbed, so these run in
CI, offline, and in a container with no outbound route.

The rate-limit tests matter disproportionately: a national backfill
runs for hours against a quota-limited free API, and getting the wait
logic wrong turns a slow job into a silently failing one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pandas as pd
import pytest

from src.data import ingestion, openmeteo
from src.data.openmeteo import (
    AIR_QUALITY_EPOCH,
    OpenMeteoError,
    _hourly_to_frame,
    _limit_kind,
    _rate_limit_wait,
)


# ──────────────────────────────────────────────────────────────
# Rate-limit classification
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "body,expected",
    [
        ("Minutely API request limit exceeded.", "minutely"),
        ("Hourly API request limit exceeded.", "hourly"),
        ("Daily API request limit exceeded.", "daily"),
        ('{"reason":"Hourly API request limit exceeded","error":true}', "hourly"),
        ("Something else entirely", "unknown"),
        ("", "unknown"),
    ],
)
def test_limit_kind_classification(body, expected):
    assert _limit_kind(body) == expected


def test_minutely_limit_uses_the_default_backoff():
    wait = _rate_limit_wait("Minutely API request limit exceeded", 65.0)
    assert wait == 65.0


def test_hourly_limit_waits_for_the_next_hour():
    """Retrying an hourly limit every 65s just burns the retry budget."""
    wait = _rate_limit_wait("Hourly API request limit exceeded", 65.0)
    now = datetime.now(UTC)
    seconds_left = (
        (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0) - now
    ).total_seconds()
    assert wait == pytest.approx(seconds_left + 30, abs=5)
    assert wait > 65.0


def test_daily_limit_waits_much_longer_than_hourly():
    hourly = _rate_limit_wait("Hourly API request limit exceeded", 65.0)
    daily = _rate_limit_wait("Daily API request limit exceeded", 65.0)
    assert daily > hourly
    assert daily <= 24 * 3600 + 120


# ──────────────────────────────────────────────────────────────
# Response parsing
# ──────────────────────────────────────────────────────────────
def test_hourly_to_frame_parses_and_renames():
    payload = {
        "hourly": {
            "time": ["2024-01-01T00:00", "2024-01-01T01:00"],
            "pm2_5": [12.3, 14.1],
        }
    }
    df = _hourly_to_frame(payload)
    assert list(df.columns) == ["timestamp", "pm2_5"]
    assert str(df["timestamp"].dt.tz) == "UTC"
    assert len(df) == 2


def test_hourly_to_frame_handles_missing_block():
    assert _hourly_to_frame({}).empty
    assert _hourly_to_frame({"hourly": {}}).empty


def test_hourly_to_frame_preserves_nulls():
    """Nulls are the signal that a date predates the archive."""
    payload = {"hourly": {"time": ["2013-01-01T00:00"], "pm2_5": [None]}}
    df = _hourly_to_frame(payload)
    assert df["pm2_5"].isna().all()


# ──────────────────────────────────────────────────────────────
# HTTP behaviour, stubbed
# ──────────────────────────────────────────────────────────────
class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def test_request_returns_payload_on_200(monkeypatch):
    monkeypatch.setattr(
        openmeteo.requests, "get", lambda *a, **k: _Response(200, {"ok": True})
    )
    assert openmeteo._request("http://x", {}) == {"ok": True}


def test_request_raises_on_client_error_without_retrying(monkeypatch):
    """A 400 will not be fixed by trying again."""
    calls = {"n": 0}

    def fake_get(*_args, **_kwargs):
        calls["n"] += 1
        return _Response(400, text="Bad parameter")

    monkeypatch.setattr(openmeteo.requests, "get", fake_get)
    with pytest.raises(OpenMeteoError, match="HTTP 400"):
        openmeteo._request("http://x", {})
    assert calls["n"] == 1


def test_request_retries_a_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_get(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Response(429, text="Minutely API request limit exceeded")
        return _Response(200, {"recovered": True})

    monkeypatch.setattr(openmeteo.requests, "get", fake_get)
    monkeypatch.setattr(openmeteo.time, "sleep", lambda _s: None)

    assert openmeteo._request("http://x", {}) == {"recovered": True}
    assert calls["n"] == 2


def test_request_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(
        openmeteo.requests,
        "get",
        lambda *a, **k: _Response(429, text="Minutely API request limit exceeded"),
    )
    monkeypatch.setattr(openmeteo.time, "sleep", lambda _s: None)
    with pytest.raises(OpenMeteoError, match="Failed after"):
        openmeteo._request("http://x", {})


def test_request_retries_network_errors(monkeypatch):
    calls = {"n": 0}

    def fake_get(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise openmeteo.requests.RequestException("connection reset")
        return _Response(200, {"ok": 1})

    monkeypatch.setattr(openmeteo.requests, "get", fake_get)
    monkeypatch.setattr(openmeteo.time, "sleep", lambda _s: None)
    assert openmeteo._request("http://x", {}) == {"ok": 1}


# ──────────────────────────────────────────────────────────────
# Fetch wrappers
# ──────────────────────────────────────────────────────────────
def _stub_request(monkeypatch, payload):
    monkeypatch.setattr(openmeteo, "_request", lambda *a, **k: payload)


def test_air_quality_archive_clamps_dates_before_the_epoch(monkeypatch):
    """Requesting 2013 returns nulls and wastes quota, so clamp it."""
    captured = {}

    def fake_request(_url, params):
        captured.update(params)
        return {"hourly": {"time": ["2022-08-05T00:00"], "pm2_5": [10.0]}}

    monkeypatch.setattr(openmeteo, "_request", fake_request)
    openmeteo.fetch_air_quality_archive(31.5, 74.3, "2013-01-01", "2013-01-02")
    assert captured["start_date"] == AIR_QUALITY_EPOCH


def test_weather_archive_does_not_clamp(monkeypatch):
    """ERA5 genuinely reaches back to 1940."""
    captured = {}

    def fake_request(_url, params):
        captured.update(params)
        return {"hourly": {"time": ["2013-01-01T00:00"], "temperature_2m": [5.0]}}

    monkeypatch.setattr(openmeteo, "_request", fake_request)
    openmeteo.fetch_weather_archive(31.5, 74.3, "2013-01-01", "2013-01-02")
    assert captured["start_date"] == "2013-01-01"


def test_batch_fetch_returns_one_frame_per_location(monkeypatch):
    blocks = [
        {"hourly": {"time": ["2024-01-01T00:00"], "pm2_5": [v]}} for v in (10, 20, 30)
    ]
    _stub_request(monkeypatch, blocks)
    frames = openmeteo.fetch_archive_batch(
        "air_quality",
        [31.5, 24.8, 33.6],
        [74.3, 67.0, 73.0],
        "2024-01-01",
        "2024-01-01",
    )
    assert len(frames) == 3
    assert frames[1]["pm2_5"].iloc[0] == 20


def test_batch_fetch_rejects_a_mismatched_block_count(monkeypatch):
    """Guessing which block belongs to which city would corrupt the data."""
    _stub_request(monkeypatch, [{"hourly": {"time": [], "pm2_5": []}}])
    with pytest.raises(OpenMeteoError, match="Expected 3 location blocks"):
        openmeteo.fetch_archive_batch(
            "air_quality",
            [1.0, 2.0, 3.0],
            [1.0, 2.0, 3.0],
            "2024-01-01",
            "2024-01-01",
        )


def test_batch_fetch_rejects_mismatched_coordinate_lengths():
    with pytest.raises(ValueError, match="same length"):
        openmeteo.fetch_archive_batch(
            "air_quality", [1.0, 2.0], [1.0], "2024-01-01", "2024-01-01"
        )


def test_batch_fetch_rejects_unknown_kind():
    with pytest.raises(ValueError, match="air_quality"):
        openmeteo.fetch_archive_batch(
            "sausages", [1.0], [1.0], "2024-01-01", "2024-01-01"
        )


def test_live_fetch_wraps_a_single_object_response(monkeypatch):
    """One coordinate returns an object; many return a list."""
    _stub_request(
        monkeypatch, {"hourly": {"time": ["2024-01-01T00:00"], "pm2_5": [9.0]}}
    )
    frames = openmeteo.fetch_air_quality_live([31.5], [74.3])
    assert len(frames) == 1


def test_probe_earliest_data_counts_non_nulls(monkeypatch):
    def fake_fetch(_lat, _lon, day, _end, variables=None):
        values = [None] * 24 if day < "2022-08-05" else [10.0] * 24
        return pd.DataFrame({"pm2_5": values})

    monkeypatch.setattr(openmeteo, "fetch_air_quality_archive", fake_fetch)
    monkeypatch.setattr(openmeteo, "polite_pause", lambda: None)

    result = openmeteo.probe_earliest_data(candidates=("2013-01-01", "2023-01-01"))
    assert result["2013-01-01"] == 0
    assert result["2023-01-01"] == 24


def test_stats_are_tracked():
    before = openmeteo.STATS.as_dict()
    assert set(before) == {"calls", "retries", "rate_limited", "failures"}


# ──────────────────────────────────────────────────────────────
# Ingestion helpers
# ──────────────────────────────────────────────────────────────
def test_month_chunks_cover_the_range_without_gaps():
    chunks = ingestion._month_chunks("2022-08-05", "2023-08-04", 6)
    assert chunks[0][0] == "2022-08-05"
    assert chunks[-1][1] == "2023-08-04"
    for (_, end), (start, _) in pairwise(chunks):
        expected = (pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat()
        assert start == expected, "chunk boundaries must be contiguous"


def test_month_chunks_handles_a_short_range():
    chunks = ingestion._month_chunks("2024-01-01", "2024-01-10", 6)
    assert chunks == [("2024-01-01", "2024-01-10")]


def test_month_chunks_crosses_a_year_boundary():
    chunks = ingestion._month_chunks("2024-11-01", "2025-03-01", 3)
    assert chunks[0][0] == "2024-11-01"
    assert chunks[-1][1] == "2025-03-01"


def test_chunk_path_is_stable_and_parseable(tmp_path):
    path = ingestion._chunk_path(tmp_path, "lahore", "2024-01-01", "2024-06-30")
    assert path.name == "lahore__2024-01-01__2024-06-30.parquet"
    assert path.name.split("__")[0] == "lahore"


def test_attach_metadata_adds_provenance_columns():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01T01:00", "2024-01-01T00:00"], utc=True
            ),
            "pm2_5": [2.0, 1.0],
        }
    )
    city = pd.Series(
        {"city_id": "lahore", "latitude": 31.5, "longitude": 74.3, "elevation_m": 217}
    )
    out = ingestion._attach_metadata(frame, city)

    assert out["city_id"].eq("lahore").all()
    assert out["data_source"].eq("open-meteo").all()
    # Sorted ascending so downstream lag features are correct.
    assert out["timestamp"].is_monotonic_increasing


def test_combine_chunks_normalises_schema_and_clamps_negatives(tmp_path, monkeypatch):
    """The two corrections that keep the dataset physically valid.

    Chunks downloaded before and after a config change carry different
    columns, and CAMS emits occasional negative concentrations.
    """
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    out_file = tmp_path / "combined.parquet"

    # `resolve()` passes absolute paths straight through, so pointing
    # the config at tmp_path is enough — no need to stub it.
    monkeypatch.setitem(ingestion._PATHS, "raw_chunks", str(chunk_dir))
    monkeypatch.setitem(ingestion._PATHS, "raw_combined", str(out_file))

    stamps = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    base = {
        "timestamp": stamps,
        "city_id": "lahore",
        "latitude": 31.5,
        "longitude": 74.3,
        "elevation_m": 217.0,
        "data_source": "open-meteo",
        "pm2_5": [10.0, 20.0, 30.0],
        "ozone": [-5.0, 10.0, 20.0],  # negative must be clamped
        "temperature_2m": [15.0, 16.0, 17.0],
        "obsolete_column": [1.0, 2.0, 3.0],  # must be dropped
    }
    pd.DataFrame(base).to_parquet(chunk_dir / "lahore__a__b.parquet", index=False)

    combined = ingestion.combine_chunks()

    assert (combined["ozone"] >= 0).all(), "negative concentrations must be clamped"
    assert "obsolete_column" not in combined.columns
    assert "pm2_5" in combined.columns
    assert combined["ingested_at"].notna().all()


def test_combine_chunks_errors_clearly_when_empty(tmp_path, monkeypatch):
    empty = tmp_path / "nothing"
    empty.mkdir()
    monkeypatch.setitem(ingestion._PATHS, "raw_chunks", str(empty))
    with pytest.raises(FileNotFoundError, match="No chunk files"):
        ingestion.combine_chunks()
