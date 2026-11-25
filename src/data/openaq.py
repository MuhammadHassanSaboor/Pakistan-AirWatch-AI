"""OpenAQ ground-truth ingestion.

Why this matters more than any other data source in the project
---------------------------------------------------------------
Our training target is CAMS reanalysis PM2.5 — a *model product*.
Without independent measurements we can only show that we forecast the
reanalysis well, which says nothing about whether we forecast the air.

OpenAQ aggregates real instruments. With it we can finally answer the
question an examiner will ask first: how close are these numbers to
what a sensor actually recorded?

What this module does NOT do
----------------------------
It does not add OpenAQ to the training set. Pakistan's monitors are
concentrated in a handful of cities and skewed towards urban roadside
sites; training on them would bake that bias into a model that claims
national coverage. OpenAQ is used for **validation only**, and the
report says so.

Station quality varies enormously — reference-grade US diplomatic
monitors sit alongside low-cost community sensors. `provider_tier`
records which is which so the evaluation can weight them differently
instead of pretending they are equivalent.

Run
---
    python -m src.data.openaq --locations       # discover and match
    python -m src.data.openaq --measurements    # pull hourly history
    python -m src.data.openaq --validate        # compare against ours
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests

from src.config import DATA_CFG, resolve, settings
from src.data.cities import load_cities

log = logging.getLogger(__name__)

_CFG = DATA_CFG.get("openaq", {})
BASE_URL = _CFG.get("base_url", "https://api.openaq.org/v3")
COUNTRY = _CFG.get("country_iso", "PK")
MAX_DISTANCE_KM = float(_CFG.get("max_distance_km", 25))

LOCATIONS_PATH = "data/raw/openaq_locations.parquet"
MEASUREMENTS_PATH = "data/raw/openaq_ground_truth.parquet"

# Reference-grade instruments we recognise by name. Everything else is
# treated as low-cost until proven otherwise — the safe default when
# the API does not expose an instrument grade.
_REFERENCE_MARKERS = ("us diplomatic post", "embassy", "consulate")


class OpenAQError(RuntimeError):
    """Raised when OpenAQ cannot be reached or refuses the request."""


def _headers() -> dict[str, str]:
    key = settings.openaq_api_key.strip()
    if not key:
        raise OpenAQError(
            "OPENAQ_API_KEY is not set. Add it to .env, or leave OpenAQ "
            "disabled in configs/data_config.yaml."
        )
    return {"X-API-Key": key, "User-Agent": "pakistan-airwatch-ai/0.1"}


def _get(path: str, params: dict[str, Any], retries: int = 4) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, headers=_headers(), timeout=60)
        except requests.RequestException as exc:
            if attempt == retries:
                raise OpenAQError(f"network error: {exc}") from exc
            time.sleep(2**attempt)
            continue

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            # OpenAQ's limit is per-minute; a short wait clears it.
            wait = min(60, 5 * attempt)
            log.warning("OpenAQ rate limited; waiting %ds", wait)
            time.sleep(wait)
            continue
        if resp.status_code in (401, 403):
            raise OpenAQError(
                f"OpenAQ rejected the API key (HTTP {resp.status_code}). "
                "Check OPENAQ_API_KEY in .env."
            )
        if attempt == retries:
            raise OpenAQError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        time.sleep(2**attempt)

    raise OpenAQError(f"failed after {retries} attempts: {url}")


def _haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Great-circle distance. Vectorised over the second pair."""
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def _classify(name: str) -> str:
    lowered = (name or "").lower()
    if any(marker in lowered for marker in _REFERENCE_MARKERS):
        return "reference"
    return "low_cost"


# ──────────────────────────────────────────────────────────────
# Location discovery
# ──────────────────────────────────────────────────────────────
def fetch_locations() -> pd.DataFrame:
    """Every Pakistani monitoring location that reports PM2.5."""
    rows: list[dict] = []
    page = 1

    while True:
        payload = _get("/locations", {"iso": COUNTRY, "limit": 1000, "page": page})
        results = payload.get("results", [])
        if not results:
            break

        for loc in results:
            coords = loc.get("coordinates") or {}
            sensors = loc.get("sensors") or []
            pm25 = [
                s for s in sensors if (s.get("parameter") or {}).get("name") == "pm25"
            ]
            if not pm25 or coords.get("latitude") is None:
                continue

            rows.append(
                {
                    "location_id": loc.get("id"),
                    "location_name": loc.get("name") or "",
                    "locality": loc.get("locality") or "",
                    "latitude": float(coords["latitude"]),
                    "longitude": float(coords["longitude"]),
                    "pm25_sensor_id": pm25[0].get("id"),
                    "provider": (loc.get("provider") or {}).get("name", ""),
                    "is_mobile": bool(loc.get("isMobile", False)),
                    "first_seen": ((loc.get("datetimeFirst") or {}) or {}).get("utc"),
                    "last_seen": ((loc.get("datetimeLast") or {}) or {}).get("utc"),
                    "provider_tier": _classify(loc.get("name") or ""),
                }
            )

        if len(results) < 1000:
            break
        page += 1
        time.sleep(0.5)

    df = pd.DataFrame(rows)
    log.info("Found %d Pakistani locations reporting PM2.5", len(df))
    return df


def match_to_cities(
    locations: pd.DataFrame, max_km: float = MAX_DISTANCE_KM
) -> pd.DataFrame:
    """Attach the nearest city to each station, within `max_km`.

    A station 60 km from the nearest city is not evidence about that
    city's air, so unmatched stations are dropped rather than stretched
    to fit.
    """
    cities = load_cities()
    if locations.empty:
        return locations.assign(city_id=None, distance_km=None)

    city_ids, distances = [], []
    for loc in locations.itertuples(index=False):
        d = _haversine_km(
            loc.latitude,
            loc.longitude,
            cities["latitude"].to_numpy(),
            cities["longitude"].to_numpy(),
        )
        i = int(np.argmin(d))
        city_ids.append(cities.iloc[i]["city_id"])
        distances.append(float(d[i]))

    out = locations.copy()
    out["city_id"] = city_ids
    out["distance_km"] = np.round(distances, 2)

    before = len(out)
    out = out[out["distance_km"] <= max_km].reset_index(drop=True)
    log.info(
        "Matched %d/%d stations to a city within %.0f km (%d cities covered)",
        len(out),
        before,
        max_km,
        out["city_id"].nunique(),
    )
    return out


# ──────────────────────────────────────────────────────────────
# Measurements
# ──────────────────────────────────────────────────────────────
def fetch_sensor_hours(
    sensor_id: int, date_from: str, date_to: str, max_pages: int = 20
) -> pd.DataFrame:
    """Hourly aggregated PM2.5 for one sensor."""
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        payload = _get(
            f"/sensors/{sensor_id}/hours",
            {
                "datetime_from": date_from,
                "datetime_to": date_to,
                "limit": 1000,
                "page": page,
            },
        )
        results = payload.get("results", [])
        if not results:
            break
        for item in results:
            period = (item.get("period") or {}).get("datetimeFrom") or {}
            rows.append(
                {
                    "sensor_id": sensor_id,
                    "timestamp": period.get("utc"),
                    "pm2_5_observed": item.get("value"),
                }
            )
        if len(results) < 1000:
            break
        time.sleep(0.3)

    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp", "pm2_5_observed"])
        # Physically impossible readings: a broken sensor, not air.
        df = df[(df["pm2_5_observed"] >= 0) & (df["pm2_5_observed"] < 2000)]
    return df


def fetch_sensor_range(
    sensor_id: int,
    start: datetime,
    end: datetime,
    chunk_days: int = 60,
) -> pd.DataFrame:
    """Hourly data over a long window, fetched in chunks.

    OpenAQ answers HTTP 408 ("provide a smaller time frame") on wide
    ranges, so a multi-year pull has to be sliced. Chunking also means
    one bad window costs that window, not the whole station.
    """
    frames: list[pd.DataFrame] = []
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    cursor = start

    while cursor < end:
        stop = min(cursor + timedelta(days=chunk_days), end)
        try:
            part = fetch_sensor_hours(
                sensor_id, cursor.strftime(fmt), stop.strftime(fmt)
            )
        except OpenAQError as exc:
            log.warning(
                "sensor %s %s..%s failed: %s",
                sensor_id,
                cursor.date(),
                stop.date(),
                exc,
            )
            part = pd.DataFrame()

        if not part.empty:
            frames.append(part)
        cursor = stop
        time.sleep(0.3)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(subset=["sensor_id", "timestamp"], keep="last")


def fetch_measurements(
    stations: pd.DataFrame, days: int = 60, limit_stations: int | None = None
) -> pd.DataFrame:
    """Hourly observations for the matched stations."""
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    # Prefer reference-grade instruments, then the closest stations.
    #
    # Sorting on provider_tier directly puts "low_cost" first because
    # it sorts before "reference" alphabetically -- the opposite of the
    # intent, and it silently starved the validation set of exactly the
    # instruments worth trusting. Rank explicitly instead.
    tier_rank = {"reference": 0, "low_cost": 1}
    ordered = (
        stations.assign(_rank=stations["provider_tier"].map(tier_rank).fillna(9))
        .sort_values(["_rank", "distance_km"])
        .drop(columns="_rank")
    )
    if limit_stations:
        ordered = ordered.head(limit_stations)

    frames: list[pd.DataFrame] = []
    for i, st in enumerate(ordered.itertuples(index=False), start=1):
        try:
            obs = fetch_sensor_hours(
                int(st.pm25_sensor_id), start.strftime(fmt), end.strftime(fmt)
            )
        except OpenAQError as exc:
            log.warning("sensor %s failed: %s", st.pm25_sensor_id, exc)
            continue

        if obs.empty:
            continue

        obs["city_id"] = st.city_id
        obs["location_id"] = st.location_id
        obs["location_name"] = st.location_name
        obs["provider_tier"] = st.provider_tier
        obs["distance_km"] = st.distance_km
        frames.append(obs)

        log.info(
            "[%d/%d] %-36s %-10s %5d hours",
            i,
            len(ordered),
            str(st.location_name)[:36],
            st.city_id,
            len(obs),
        )
        time.sleep(0.3)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["sensor_id", "timestamp"], keep="last")
    return df.sort_values(["city_id", "timestamp"]).reset_index(drop=True)


# ──────────────────────────────────────────────────────────────
# Validation against our own data
# ──────────────────────────────────────────────────────────────
def validate_against_reanalysis(
    observations: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compare CAMS reanalysis with real sensor readings.

    This quantifies the project's headline limitation. If the
    reanalysis tracks the sensors closely, forecasting it is a
    reasonable proxy for forecasting reality; if it does not, we say so
    with a number instead of a caveat.
    """
    if observations is None:
        path = resolve(MEASUREMENTS_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"No OpenAQ data at {path}. Run --measurements first."
            )
        observations = pd.read_parquet(path)

    ours = pd.read_parquet(resolve(DATA_CFG["paths"]["raw_combined"]))
    ours["timestamp"] = pd.to_datetime(ours["timestamp"], utc=True)
    ours = ours[["city_id", "timestamp", "pm2_5"]].rename(
        columns={"pm2_5": "pm2_5_reanalysis"}
    )

    obs = observations.copy()
    obs["timestamp"] = pd.to_datetime(obs["timestamp"], utc=True).dt.floor("h")

    merged = obs.merge(ours, on=["city_id", "timestamp"], how="inner")
    merged = merged.dropna(subset=["pm2_5_observed", "pm2_5_reanalysis"])

    if merged.empty:
        return {
            "status": "no_overlap",
            "message": (
                "No overlapping hours. The local dataset and the OpenAQ "
                "window may not intersect; widen --days or backfill more."
            ),
            "observation_rows": int(len(obs)),
        }

    def _stats(frame: pd.DataFrame) -> dict[str, float]:
        e = frame["pm2_5_reanalysis"] - frame["pm2_5_observed"]
        return {
            "n": int(len(frame)),
            "mae": round(float(e.abs().mean()), 3),
            "bias": round(float(e.mean()), 3),
            "rmse": round(float(np.sqrt((e**2).mean())), 3),
            "correlation": round(
                float(frame["pm2_5_reanalysis"].corr(frame["pm2_5_observed"])),
                4,
            ),
            "mean_observed": round(float(frame["pm2_5_observed"].mean()), 2),
        }

    report: dict[str, Any] = {
        "status": "ok",
        "generated_at": datetime.now(UTC).isoformat(),
        "overall": _stats(merged),
        "by_tier": {
            tier: _stats(part)
            for tier, part in merged.groupby("provider_tier")
            if len(part) >= 30
        },
        "by_city": {
            city: _stats(part)
            for city, part in merged.groupby("city_id")
            if len(part) >= 50
        },
        "interpretation": (
            "A positive bias means the reanalysis reads HIGHER than the "
            "instruments. Reference-grade stations are the trustworthy "
            "comparison; low-cost sensors commonly over-report humidity-"
            "affected particulate and should be read with that in mind."
        ),
    }

    out = resolve("reports/ground_truth_validation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Validation report -> %s", out)
    return report


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="OpenAQ ground-truth ingestion")
    ap.add_argument("--locations", action="store_true", help="discover and match")
    ap.add_argument("--measurements", action="store_true", help="pull hourly data")
    ap.add_argument("--validate", action="store_true", help="compare with ours")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--limit-stations", type=int, default=40)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    if args.all or args.locations:
        locations = fetch_locations()
        matched = match_to_cities(locations)
        path = resolve(LOCATIONS_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        matched.to_parquet(path, index=False)
        print(f"\n{len(matched)} stations matched -> {path}")
        if not matched.empty:
            print(matched["provider_tier"].value_counts().to_string())
            print("\nCities with ground truth:")
            top = (
                matched.groupby("city_id").size().sort_values(ascending=False).head(15)
            )
            print(top.to_string())

    if args.all or args.measurements:
        path = resolve(LOCATIONS_PATH)
        if not path.exists():
            raise SystemExit("Run --locations first.")
        stations = pd.read_parquet(path)
        obs = fetch_measurements(
            stations, days=args.days, limit_stations=args.limit_stations
        )
        if obs.empty:
            print("No measurements returned.")
        else:
            out = resolve(MEASUREMENTS_PATH)
            obs.to_parquet(out, index=False)
            print(f"\n{len(obs):,} hourly observations -> {out}")
            print(
                f"Cities: {obs.city_id.nunique()}  Stations: {obs.sensor_id.nunique()}"
            )
            print(f"Range : {obs.timestamp.min()} -> {obs.timestamp.max()}")

    if args.all or args.validate:
        report = validate_against_reanalysis()
        if report["status"] != "ok":
            print(report["message"])
            return
        o = report["overall"]
        print("\n=== CAMS reanalysis vs real instruments ===")
        print(f"  matched hours : {o['n']:,}")
        print(f"  MAE           : {o['mae']} ug/m3")
        print(f"  bias          : {o['bias']:+} ug/m3")
        print(f"  correlation   : {o['correlation']}")
        print(f"  mean observed : {o['mean_observed']} ug/m3")
        for tier, s in report["by_tier"].items():
            print(
                f"\n  {tier:<10} n={s['n']:>6}  MAE={s['mae']:>7}  "
                f"bias={s['bias']:>+8}  r={s['correlation']}"
            )

    if not any([args.all, args.locations, args.measurements, args.validate]):
        ap.print_help()


if __name__ == "__main__":
    main()
