"""Live feature provider for the serving layer.

Builds model-ready features for *right now* using the SAME functions
the training pipeline uses (`src.features.preprocessing`). Importing
the identical code is what prevents training/serving skew: there is no
second implementation that can drift.

Data flow:

    Open-Meteo live endpoint  ->  recent hourly observations
                              ->  src.features.preprocessing
                              ->  latest row per city  ->  model

Responses are cached for an hour because the upstream data only
updates hourly. Without the cache, every map pan would hit Open-Meteo
and we would be rate-limited within minutes.

Degradation ladder
------------------
A forecasting dashboard that goes blank when a free API hits its daily
quota is not much of a dashboard, so the store falls back in order:

    1. fresh upstream data            source = "live"
    2. the previous cache, stale      source = "stale_cache"
    3. the local historical dataset   source = "historical"
    4. nothing -> 503 with a reason   source = "none"

Before any of that has been attempted the store reports "warming",
which is distinct from "none": one means no fetch has happened yet,
the other means every fetch route was tried and failed.

Every level reports which one it used, so the API and the UI can say
plainly whether a number is current or carried over. Silently serving
stale data as if it were live would be the dishonest option.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

import pandas as pd

from src.config import DATA_CFG, resolve
from src.data.cities import load_cities
from src.data.openmeteo import (
    OpenMeteoError,
    fetch_air_quality_live,
    fetch_weather_forecast,
)
from src.features.preprocessing import (
    add_calendar_features,
    add_lag_features,
    add_spatial_features,
    add_static_features,
    add_weather_features,
)

log = logging.getLogger(__name__)

CACHE_TTL = timedelta(minutes=55)
BATCH_SIZE = 12


class LiveFeatureStore:
    """Fetches and caches recent observations, then derives features."""

    def __init__(self, ttl: timedelta = CACHE_TTL) -> None:
        self._lock = threading.Lock()
        self._ttl = ttl
        self._observations: pd.DataFrame | None = None
        self._features: pd.DataFrame | None = None
        self._fetched_at: datetime | None = None
        self._cities = load_cities()
        self._source: str = "none"
        self._last_error: str | None = None
        # Don't retry upstream on every single request once it has
        # failed; that turns a quota exhaustion into a slow 503 storm.
        self._retry_after: datetime | None = None

    # ── cache ─────────────────────────────────────────────────
    @property
    def is_stale(self) -> bool:
        if self._fetched_at is None or self._features is None:
            return True
        return datetime.now(UTC) - self._fetched_at > self._ttl

    @property
    def age_seconds(self) -> float | None:
        if self._fetched_at is None:
            return None
        return (datetime.now(UTC) - self._fetched_at).total_seconds()

    def status(self) -> dict:
        # A store that has never been asked for data is NOT a store that
        # failed. /health only reads status(), it never calls refresh(),
        # so on a cold process `_source` is still its initial "none" --
        # and the dashboard rendered that as "Neither the upstream feed
        # nor the local dataset is available", which is alarming and
        # untrue. "warming" says what is actually happening: no fetch
        # has been attempted yet. The first request for features turns
        # it into live / stale_cache / historical, and only a real
        # failure (recorded in _last_error) ever reports "none".
        if self._features is None and self._last_error is None:
            source = "warming"
        else:
            source = self._source

        return {
            "cached": self._features is not None,
            "fetched_at": self._fetched_at.isoformat() if self._fetched_at else None,
            "age_seconds": round(self.age_seconds, 1) if self.age_seconds else None,
            "stale": self.is_stale,
            # Which rung of the degradation ladder produced the data
            # currently being served:
            # warming | live | stale_cache | historical | none.
            "source": source,
            "upstream_error": self._last_error,
            "cities": int(self._features.city_id.nunique())
            if self._features is not None
            else 0,
            "rows": int(len(self._features)) if self._features is not None else 0,
        }

    @property
    def source(self) -> str:
        return self._source

    # ── fetching ──────────────────────────────────────────────
    def _fetch_observations(self) -> pd.DataFrame:
        """Recent + forecast hours for every city, in batches."""
        frames: list[pd.DataFrame] = []
        cities = self._cities

        for i in range(0, len(cities), BATCH_SIZE):
            batch = cities.iloc[i : i + BATCH_SIZE]
            lats = batch["latitude"].tolist()
            lons = batch["longitude"].tolist()

            aq_blocks = fetch_air_quality_live(lats, lons)
            wx_blocks = fetch_weather_forecast(lats, lons)

            for j, city in enumerate(batch.itertuples(index=False)):
                aq = aq_blocks[j] if j < len(aq_blocks) else pd.DataFrame()
                wx = wx_blocks[j] if j < len(wx_blocks) else pd.DataFrame()
                if aq.empty and wx.empty:
                    continue
                if aq.empty:
                    merged = wx
                elif wx.empty:
                    merged = aq
                else:
                    merged = aq.merge(wx, on="timestamp", how="outer")

                merged["city_id"] = city.city_id
                merged["latitude"] = float(city.latitude)
                merged["longitude"] = float(city.longitude)
                merged["elevation_m"] = int(city.elevation_m)
                merged["data_source"] = "open-meteo"
                frames.append(merged)

        if not frames:
            raise RuntimeError("Open-Meteo returned no live data for any city")

        df = pd.concat(frames, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df.sort_values(["city_id", "timestamp"]).reset_index(drop=True)

    def _build_features(self, obs: pd.DataFrame) -> pd.DataFrame:
        """Apply the training-time transformations, in the same order."""
        df = obs.copy()
        extra = [
            c
            for c in ("city_name", "province", "population")
            if c in self._cities.columns
        ]
        df = df.merge(self._cities[["city_id", *extra]], on="city_id", how="left")

        df = add_calendar_features(df)
        df = add_lag_features(df)
        df = add_weather_features(df)
        df = add_spatial_features(df)
        df = add_static_features(df)
        return df

    def _load_historical(self, days: int = 10) -> pd.DataFrame:
        """Most recent slice of the local dataset, as a last resort.

        Lets the dashboard stay useful when the free upstream quota is
        exhausted, which on a free tier is a routine condition rather
        than an outage. The data is real and ours; it is simply not
        current, and the API labels it so.
        """
        path = resolve(DATA_CFG["paths"]["raw_combined"])
        if not path.exists():
            raise FileNotFoundError(
                f"No local dataset at {path}; run python -m src.data.ingestion"
            )
        df = pd.read_parquet(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        cutoff = df["timestamp"].max() - timedelta(days=days)
        df = df[df["timestamp"] >= cutoff]
        return df.sort_values(["city_id", "timestamp"]).reset_index(drop=True)

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and not self.is_stale:
                return

            now = datetime.now(UTC)
            backing_off = self._retry_after is not None and now < self._retry_after

            obs: pd.DataFrame | None = None
            source = "none"

            if not backing_off:
                try:
                    log.info(
                        "Refreshing live features for %d cities...",
                        len(self._cities),
                    )
                    obs = self._fetch_observations()
                    source = "live"
                    self._last_error = None
                    self._retry_after = None
                except (OpenMeteoError, RuntimeError) as exc:
                    self._last_error = str(exc)[:300]
                    # Upstream is out for a while; stop hammering it.
                    self._retry_after = now + timedelta(minutes=15)
                    log.warning("Live fetch failed: %s", exc)
            else:
                self._last_error = self._last_error or "upstream backoff in effect"

            if obs is None and self._features is not None:
                # Keep serving the previous cache rather than going blank.
                log.warning("Serving stale cache (upstream unavailable)")
                self._source = "stale_cache"
                return

            if obs is None:
                try:
                    obs = self._load_historical()
                    source = "historical"
                    log.warning(
                        "Falling back to the local historical dataset "
                        "(%d rows, latest %s)",
                        len(obs),
                        obs["timestamp"].max(),
                    )
                except Exception as exc:  # nothing left to serve
                    self._last_error = f"{self._last_error or ''} | {exc}"[:300]
                    log.error("No data available from any source: %s", exc)
                    return

            self._observations = obs
            self._features = self._build_features(obs)
            self._source = source
            self._fetched_at = datetime.now(UTC)
            log.info(
                "Live cache ready: %d rows, %d cities, latest %s",
                len(self._features),
                self._features.city_id.nunique(),
                self._features.timestamp.max(),
            )

    # ── public API ────────────────────────────────────────────
    def latest_features(self, city_ids: list[str] | None = None) -> pd.DataFrame:
        """Most recent *complete* feature row per city.

        Rows whose timestamp lies in the future are dropped: the live
        endpoint returns forecast hours too, and predicting from a row
        that does not exist yet would be meaningless.
        """
        self.refresh()
        if self._features is None:
            return pd.DataFrame()

        now = pd.Timestamp.now(tz="UTC")
        df = self._features[self._features["timestamp"] <= now]

        lag_col = "pm2_5_lag_1h"
        if lag_col in df.columns:
            df = df[df[lag_col].notna()]

        if city_ids:
            df = df[df["city_id"].isin(city_ids)]

        if df.empty:
            return df
        return (
            df.sort_values("timestamp")
            .groupby("city_id", as_index=False)
            .tail(1)
            .reset_index(drop=True)
        )

    def recent_observations(self, city_id: str, days: int = 7) -> pd.DataFrame:
        """Observed history for the city-detail chart."""
        self.refresh()
        if self._observations is None:
            return pd.DataFrame()
        cutoff = pd.Timestamp.now(tz="UTC") - timedelta(days=days)
        df = self._observations[
            (self._observations["city_id"] == city_id)
            & (self._observations["timestamp"] >= cutoff)
        ]
        return df.sort_values("timestamp").reset_index(drop=True)

    def provider_forecast(self, city_id: str) -> pd.DataFrame:
        """Open-Meteo's OWN forward hours.

        Kept strictly separate from our model's predictions. Showing
        them as the same thing would misrepresent provenance, which the
        requirements call out explicitly.
        """
        self.refresh()
        if self._observations is None:
            return pd.DataFrame()
        now = pd.Timestamp.now(tz="UTC")
        df = self._observations[
            (self._observations["city_id"] == city_id)
            & (self._observations["timestamp"] > now)
        ]
        return df.sort_values("timestamp").reset_index(drop=True)


_store: LiveFeatureStore | None = None


def get_store() -> LiveFeatureStore:
    """Process-wide singleton so the cache is shared across requests."""
    global _store
    if _store is None:
        _store = LiveFeatureStore()
    return _store


__all__ = ["LiveFeatureStore", "get_store"]
