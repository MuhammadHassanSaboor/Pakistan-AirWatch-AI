"""Open-Meteo API client.

Open-Meteo requires **no API key and no account**. This is the reason
the whole project can run on free resources: it supplies both the
pollutant history (CAMS reanalysis) and the weather history (ERA5),
hourly, for any coordinate on earth.

Two important facts, verified against the live API on 2026-11-25 and
recorded in Documents/DATA_FEASIBILITY.md:

1. The air-quality archive ACCEPTS dates back to 2013 but returns
   all-null values before **2022-08-05**. Requesting earlier dates
   wastes quota and yields nothing.
2. The weather archive (ERA5) genuinely reaches back to 1940.

Terms: free for non-commercial use, attribution required. We credit
Open-Meteo in the README, the report and the web app footer.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from src.config import DATA_CFG

log = logging.getLogger(__name__)

_AQ = DATA_CFG["openmeteo_air_quality"]
_WX = DATA_CFG["openmeteo_weather"]
_FETCH = DATA_CFG["fetch"]

# Earliest date with real (non-null) pollutant data.
AIR_QUALITY_EPOCH = DATA_CFG["time"]["air_quality_start"]

USER_AGENT = "pakistan-airwatch-ai/0.1 (academic MLOps course project)"


class OpenMeteoError(RuntimeError):
    """Raised when the API cannot be reached after all retries."""


@dataclass
class FetchStats:
    """Counters for observability; surfaced in the ingestion report."""

    calls: int = 0
    retries: int = 0
    rate_limited: int = 0
    failures: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "retries": self.retries,
            "rate_limited": self.rate_limited,
            "failures": self.failures,
        }


STATS = FetchStats()


def _limit_kind(body: str) -> str:
    """Which quota the 429 refers to: minutely, hourly or daily."""
    text = (body or "").lower()
    for kind in ("minutely", "hourly", "daily"):
        if kind in text:
            return kind
    return "unknown"


def _rate_limit_wait(body: str, default: float) -> float:
    """How long to wait after a 429.

    Open-Meteo enforces separate per-minute, per-hour and per-day
    quotas. Retrying an *hourly* limit every 65 seconds just burns the
    retry budget and fails the batch, so we wait for the quota window
    to actually roll over. The difference matters: a national backfill
    takes several hours of wall-clock time and must survive unattended.
    """
    kind = _limit_kind(body)
    now = datetime.now(UTC)

    if kind == "hourly":
        next_hour = (now + timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0
        )
        return (next_hour - now).total_seconds() + 30

    if kind == "daily":
        next_day = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return (next_day - now).total_seconds() + 60

    # minutely or unknown
    return default


def _request(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET with retries, exponential backoff and 429 handling."""
    max_retries = int(_FETCH["max_retries"])
    backoff = float(_FETCH["backoff_seconds"])
    timeout = float(_FETCH["timeout_seconds"])
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            STATS.calls += 1
            resp = requests.get(
                url,
                params=params,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.RequestException as exc:
            last_error = exc
            STATS.retries += 1
            wait = min(backoff, 2**attempt)
            log.warning(
                "Network error (attempt %d/%d): %s — retrying in %.0fs",
                attempt,
                max_retries,
                exc,
                wait,
            )
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            STATS.rate_limited += 1
            STATS.retries += 1
            wait = _rate_limit_wait(resp.text, backoff)
            log.warning(
                "Rate limited (429): %s Sleeping %.0fs before retry %d/%d.",
                _limit_kind(resp.text),
                wait,
                attempt,
                max_retries,
            )
            time.sleep(wait)
            continue

        # 4xx other than 429 will not be fixed by retrying.
        if 400 <= resp.status_code < 500:
            STATS.failures += 1
            raise OpenMeteoError(
                f"HTTP {resp.status_code} from Open-Meteo: {resp.text[:300]}"
            )

        # 5xx — worth retrying.
        last_error = OpenMeteoError(f"HTTP {resp.status_code}")
        STATS.retries += 1
        time.sleep(min(backoff, 2**attempt))

    STATS.failures += 1
    raise OpenMeteoError(
        f"Failed after {max_retries} attempts: {url} params={params} "
        f"last_error={last_error}"
    )


def _hourly_to_frame(payload: dict[str, Any]) -> pd.DataFrame:
    """Convert an Open-Meteo 'hourly' block into a tidy DataFrame."""
    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        return pd.DataFrame()
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.rename(columns={"time": "timestamp"})


def fetch_air_quality_archive(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: list[str] | None = None,
) -> pd.DataFrame:
    """Historical hourly pollutants for one coordinate."""
    if start_date < AIR_QUALITY_EPOCH:
        log.debug(
            "Clamping start_date %s to air-quality epoch %s",
            start_date,
            AIR_QUALITY_EPOCH,
        )
        start_date = AIR_QUALITY_EPOCH

    payload = _request(
        _AQ["archive_url"],
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(variables or _AQ["variables"]),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "UTC",
        },
    )
    return _hourly_to_frame(payload)


def fetch_weather_archive(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: list[str] | None = None,
) -> pd.DataFrame:
    """Historical hourly ERA5 weather for one coordinate."""
    payload = _request(
        _WX["archive_url"],
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(variables or _WX["variables"]),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "UTC",
        },
    )
    return _hourly_to_frame(payload)


def fetch_archive_batch(
    kind: str,
    latitudes: list[float],
    longitudes: list[float],
    start_date: str,
    end_date: str,
    variables: list[str] | None = None,
) -> list[pd.DataFrame]:
    """Historical data for MANY coordinates in a SINGLE request.

    Open-Meteo accepts comma-separated coordinates on the archive
    endpoints and returns a JSON list, one block per location, in the
    order requested. This is the difference between ~1,300 requests and
    ~200 for a full national backfill.

    Note on limits: request "weight" scales with
    locations x days x variables, so very large batches trip the
    per-minute limit. Measured on 2026-11-25: 20 cities x 1 year
    succeeded, 30 returned HTTP 429. `configs/data_config.yaml`
    keeps the batch size well under that ceiling.

    Parameters
    ----------
    kind : "air_quality" or "weather"
    """
    if len(latitudes) != len(longitudes):
        raise ValueError("latitudes and longitudes must be the same length")
    if kind not in {"air_quality", "weather"}:
        raise ValueError(f"kind must be 'air_quality' or 'weather', got {kind!r}")

    if kind == "air_quality":
        url = _AQ["archive_url"]
        default_vars = _AQ["variables"]
        if start_date < AIR_QUALITY_EPOCH:
            start_date = AIR_QUALITY_EPOCH
    else:
        url = _WX["archive_url"]
        default_vars = _WX["variables"]

    payload = _request(
        url,
        {
            "latitude": ",".join(f"{v:.4f}" for v in latitudes),
            "longitude": ",".join(f"{v:.4f}" for v in longitudes),
            "hourly": ",".join(variables or default_vars),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "UTC",
        },
    )
    blocks = payload if isinstance(payload, list) else [payload]

    if len(blocks) != len(latitudes):
        raise OpenMeteoError(
            f"Expected {len(latitudes)} location blocks, received "
            f"{len(blocks)}. Refusing to guess the mapping."
        )
    return [_hourly_to_frame(b) for b in blocks]


def fetch_air_quality_live(
    latitudes: list[float],
    longitudes: list[float],
    past_days: int | None = None,
    forecast_days: int | None = None,
) -> list[pd.DataFrame]:
    """Recent + forecast pollutants for MANY coordinates in one call.

    Open-Meteo accepts comma-separated coordinates and returns a JSON
    list, one object per location, in the order requested. Batching
    keeps our hourly refresh to a handful of calls instead of 130.
    """
    if len(latitudes) != len(longitudes):
        raise ValueError("latitudes and longitudes must be the same length")

    payload = _request(
        _AQ["live_url"],
        {
            "latitude": ",".join(f"{v:.4f}" for v in latitudes),
            "longitude": ",".join(f"{v:.4f}" for v in longitudes),
            "hourly": ",".join(_AQ["variables"]),
            "past_days": past_days or _AQ["live"]["past_days"],
            "forecast_days": forecast_days or _AQ["live"]["forecast_days"],
            "timezone": "UTC",
        },
    )
    # A single coordinate returns an object, many return a list.
    blocks = payload if isinstance(payload, list) else [payload]
    return [_hourly_to_frame(b) for b in blocks]


def fetch_weather_forecast(
    latitudes: list[float],
    longitudes: list[float],
    past_days: int | None = None,
    forecast_days: int | None = None,
) -> list[pd.DataFrame]:
    """Recent + forecast weather for MANY coordinates in one call."""
    if len(latitudes) != len(longitudes):
        raise ValueError("latitudes and longitudes must be the same length")

    payload = _request(
        _WX["forecast_url"],
        {
            "latitude": ",".join(f"{v:.4f}" for v in latitudes),
            "longitude": ",".join(f"{v:.4f}" for v in longitudes),
            "hourly": ",".join(_WX["variables"]),
            "past_days": past_days or _AQ["live"]["past_days"],
            "forecast_days": forecast_days or _AQ["live"]["forecast_days"],
            "timezone": "UTC",
        },
    )
    blocks = payload if isinstance(payload, list) else [payload]
    return [_hourly_to_frame(b) for b in blocks]


def polite_pause() -> None:
    """Sleep between calls so we stay well inside fair-use limits."""
    time.sleep(float(_FETCH["sleep_seconds"]))


def probe_earliest_data(
    latitude: float = 31.5204,
    longitude: float = 74.3587,
    candidates: tuple[str, ...] = (
        "2013-01-01",
        "2019-01-01",
        "2022-08-01",
        "2022-08-05",
        "2022-10-01",
    ),
) -> dict[str, int]:
    """Diagnostic: how many non-null PM2.5 hours each date returns.

    Used by scripts/check_data_feasibility.py so the team can re-verify
    source coverage at any time rather than trusting documentation.
    """
    out: dict[str, int] = {}
    for day in candidates:
        try:
            df = fetch_air_quality_archive(
                latitude, longitude, day, day, variables=["pm2_5"]
            )
            out[day] = int(df["pm2_5"].notna().sum()) if "pm2_5" in df else 0
        except OpenMeteoError as exc:
            log.warning("Probe failed for %s: %s", day, exc)
            out[day] = -1
        polite_pause()
    return out


__all__ = [
    "AIR_QUALITY_EPOCH",
    "OpenMeteoError",
    "STATS",
    "fetch_air_quality_archive",
    "fetch_weather_archive",
    "fetch_archive_batch",
    "fetch_air_quality_live",
    "fetch_weather_forecast",
    "polite_pause",
    "probe_earliest_data",
]
