"""Feast materialisation and retrieval demonstration.

Proves the full feature-store loop the specification requires:

    1. apply        register the definitions
    2. materialize  copy offline (parquet) -> online (SQLite)
    3. online read  low-latency lookup for serving
    4. offline read point-in-time correct join for training

Run
---
    python feature_store/materialize.py --prepare   # build sources
    python feature_store/materialize.py --apply
    python feature_store/materialize.py --materialize
    python feature_store/materialize.py --demo
    python feature_store/materialize.py --all
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DATA_CFG, resolve  # noqa: E402
from src.data.cities import load_cities  # noqa: E402

log = logging.getLogger(__name__)

REPO_PATH = PROJECT_ROOT / "feature_store" / "feature_repo"


def prepare_sources() -> None:
    """Build the parquet files the feature views point at.

    `city_static` needs a timestamp column even though geography does
    not change: Feast requires an event timestamp on every source so
    that point-in-time joins remain well-defined.
    """
    cities = load_cities()
    import numpy as np

    static = pd.DataFrame(
        {
            "city_id": cities["city_id"],
            "latitude": cities["latitude"].astype("float32"),
            "longitude": cities["longitude"].astype("float32"),
            "elevation_m": cities["elevation_m"].astype("float32"),
            "log_population": np.log1p(cities["population"]).astype("float32"),
            "province": cities["province"].astype(str),
            # A single old timestamp makes these rows valid for every
            # later point-in-time lookup.
            "timestamp": pd.Timestamp("2020-01-01", tz="UTC"),
        }
    )

    out = resolve("data/processed/city_static.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    static.to_parquet(out, index=False)
    log.info("Wrote %d static city rows -> %s", len(static), out)

    features_path = resolve(DATA_CFG["paths"]["processed"])
    if not features_path.exists():
        log.warning(
            "Feature table missing at %s. Run: python -m src.features.build_features",
            features_path,
        )
        return

    # Feast needs ONE row per (entity, event_timestamp). The supervised
    # table carries four rows per city-hour -- one per forecast horizon
    # -- because `horizon` is a training-time feature. Feeding those
    # duplicate keys into a point-in-time join silently returns nothing.
    #
    # The horizon expansion is a training concern, not a feature-store
    # concern, so we project the supervised table back down to the
    # observation grain here.
    wanted = [
        "city_id",
        "timestamp",
        "pm2_5_lag_1h",
        "pm2_5_lag_24h",
        "pm2_5_lag_168h",
        "pm2_5_roll24_mean",
        "pm2_5_roll24_std",
        "pm2_5_roll72_mean",
        "pm2_5_diff_24h",
        "neighbour_pm25_lag1h",
        "temperature_2m",
        "relative_humidity_2m",
        "wind_speed_10m",
        "wind_u",
        "wind_v",
        "boundary_layer_height",
        "ventilation_index",
        "precipitation",
        "hour",
        "day_of_week",
        "month",
        "hour_sin",
        "hour_cos",
        "is_smog_season",
        "is_burning_window",
    ]
    full = pd.read_parquet(features_path)
    cols = [c for c in wanted if c in full.columns]
    grain = (
        full[cols]
        .drop_duplicates(subset=["city_id", "timestamp"], keep="first")
        .sort_values(["city_id", "timestamp"])
        .reset_index(drop=True)
    )
    for col in ("hour", "day_of_week", "month", "is_smog_season", "is_burning_window"):
        if col in grain.columns:
            grain[col] = grain[col].astype("int64")

    feast_path = resolve("data/processed/feast_features.parquet")
    grain.to_parquet(feast_path, index=False)
    log.info(
        "Wrote %d observation-grain rows (%d cities) -> %s",
        len(grain),
        grain.city_id.nunique(),
        feast_path,
    )


def _feast(*args: str) -> int:
    """Run a feast CLI command inside the feature repo."""
    # `python -m feast` does not work: feast ships a console script,
    # not a __main__ module. Resolve the installed executable instead.
    feast_bin = shutil.which("feast")
    cmd = (
        [feast_bin, *args] if feast_bin else [sys.executable, "-m", "feast.cli", *args]
    )
    log.info("$ feast %s", " ".join(args))
    result = subprocess.run(cmd, cwd=REPO_PATH, check=False)
    return result.returncode


def apply_definitions() -> int:
    return _feast("apply")


def materialize(days: int = 7) -> int:
    """Copy features from the offline store into the online store.

    Two passes, because the views have very different event-time
    behaviour. The hourly views only need a recent window. The static
    view carries a single 2020 timestamp per city, so a "last 7 days"
    window materialises nothing from it -- which is why elevation came
    back as null until this was split out.
    """
    end = datetime.now(UTC)
    fmt = "%Y-%m-%dT%H:%M:%S"

    code = _feast(
        "materialize",
        datetime(2019, 1, 1, tzinfo=UTC).strftime(fmt),
        end.strftime(fmt),
        "--views",
        "city_static",
    )
    if code != 0:
        return code

    start = end - timedelta(days=days)
    for view in ("city_pollution_lags", "city_weather_hourly", "city_calendar"):
        code = _feast(
            "materialize", start.strftime(fmt), end.strftime(fmt), "--views", view
        )
        if code != 0:
            return code
    return 0


def demo_retrieval() -> None:
    """Show both retrieval paths working."""
    from feast import FeatureStore

    # Feast resolves a FileSource's relative path against the CURRENT
    # WORKING DIRECTORY, not against repo_path. The CLI happens to run
    # inside the repo directory, so paths that work under `feast
    # materialize` break when the same store is opened from Python.
    # Changing directory keeps both paths identical and avoids baking
    # machine-specific absolute paths into the feature definitions.
    original_cwd = os.getcwd()
    os.chdir(REPO_PATH)
    try:
        _demo_retrieval_inner(FeatureStore(repo_path="."), original_cwd)
    finally:
        os.chdir(original_cwd)


def _demo_retrieval_inner(store, original_cwd: str) -> None:
    online_features = [
        "city_pollution_lags:pm2_5_lag_1h",
        "city_pollution_lags:pm2_5_lag_24h",
        "city_pollution_lags:pm2_5_roll24_mean",
        "city_weather_hourly:temperature_2m",
        "city_weather_hourly:wind_speed_10m",
        "city_weather_hourly:ventilation_index",
        "city_static:elevation_m",
    ]

    print("\n" + "=" * 62)
    print("ONLINE RETRIEVAL  (serving path, low latency)")
    print("=" * 62)

    # Pick cities that are actually present in the materialised
    # store, so the demo does not look broken while the national
    # backfill is still running.
    available = (
        pd.read_parquet(
            pathlib.Path(original_cwd)
            / "data"
            / "processed"
            / "feast_features.parquet",
            columns=["city_id"],
        )["city_id"]
        .drop_duplicates()
        .tolist()
    )
    preferred = ["lahore", "karachi", "islamabad", "quetta", "peshawar"]
    chosen = [c for c in preferred if c in available] or available[:4]
    entity_rows = [{"city_id": c} for c in chosen[:4]]

    import time

    started = time.perf_counter()
    online = store.get_online_features(
        features=online_features, entity_rows=entity_rows
    ).to_df()
    elapsed_ms = (time.perf_counter() - started) * 1000

    print(online.to_string(index=False))
    print(f"\nRetrieved {len(online)} entities in {elapsed_ms:.1f} ms")

    print("\n" + "=" * 62)
    print("OFFLINE RETRIEVAL  (training path, point-in-time correct)")
    print("=" * 62)

    grain_path = (
        pathlib.Path(original_cwd) / "data" / "processed" / "feast_features.parquet"
    )
    if not grain_path.exists():
        print("Feature table not built yet; skipping the offline demo.")
        return

    # The entity frame must carry UNIQUE (entity, event_timestamp)
    # pairs. Sampling from the supervised table instead produces four
    # rows per city-hour (one per horizon) and the point-in-time join
    # silently returns nothing.
    sample = pd.read_parquet(grain_path, columns=["city_id", "timestamp"])
    sample = sample.drop_duplicates(subset=["city_id", "timestamp"])
    entity_df = sample.sample(min(8, len(sample)), random_state=42).copy()
    entity_df = entity_df.rename(columns={"timestamp": "event_timestamp"})
    entity_df = entity_df.sort_values("event_timestamp").reset_index(drop=True)

    training_df = store.get_historical_features(
        entity_df=entity_df,
        features=online_features,
    ).to_df()

    print(training_df.to_string(index=False))
    print(
        f"\nJoined {len(training_df)} training rows. Each row carries the "
        "feature values as they were AT that row's timestamp, not the "
        "latest values.\nThat point-in-time correctness is what keeps the "
        "training set free of look-ahead leakage."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Feast operations")
    parser.add_argument("--prepare", action="store_true", help="build source files")
    parser.add_argument("--apply", action="store_true", help="feast apply")
    parser.add_argument("--materialize", action="store_true", help="offline -> online")
    parser.add_argument("--demo", action="store_true", help="retrieval demo")
    parser.add_argument("--all", action="store_true", help="run every step")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    if args.all or args.prepare:
        prepare_sources()
    if (args.all or args.apply) and apply_definitions() != 0:
        sys.exit("feast apply failed")
    if (args.all or args.materialize) and materialize(args.days) != 0:
        sys.exit("feast materialize failed")
    if args.all or args.demo:
        demo_retrieval()

    if not any([args.prepare, args.apply, args.materialize, args.demo, args.all]):
        parser.print_help()


if __name__ == "__main__":
    main()
