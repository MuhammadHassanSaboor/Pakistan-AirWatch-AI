"""Historical data ingestion.

Downloads hourly air-quality and weather history for every city in the
reference table and assembles one combined parquet file.

Design notes
------------
* **Batched.** Open-Meteo accepts many coordinates per request, so we
  fetch a dozen cities at a time. A national backfill costs roughly
  200 requests instead of 1,300 — the difference between 40 minutes
  and three hours.
* **Resumable.** Each (city, date-chunk) lands in its own parquet
  file. Re-running skips what already exists, so an interrupted
  download costs nothing.
* **Polite.** A pause between requests plus HTTP 429 backoff keeps us
  inside Open-Meteo's fair-use limits. Do not remove the sleep.
* **Honest about gaps.** Failed batches are recorded in the ingestion
  report rather than silently dropped.

Run
---
    python -m src.data.ingestion                 # full backfill
    python -m src.data.ingestion --limit 12      # quick smoke test
    python -m src.data.ingestion --combine-only  # rebuild from chunks
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.config import DATA_CFG, resolve
from src.data.cities import load_cities
from src.data.openmeteo import (
    STATS,
    OpenMeteoError,
    fetch_archive_batch,
    polite_pause,
)

log = logging.getLogger(__name__)

_PATHS = DATA_CFG["paths"]
_TIME = DATA_CFG["time"]
_FETCH = DATA_CFG["fetch"]


def _month_chunks(start: str, end: str, months: int) -> list[tuple[str, str]]:
    """Split a date range into chunks of N months."""
    out: list[tuple[str, str]] = []
    cur = date.fromisoformat(start)
    final = date.fromisoformat(end)

    while cur <= final:
        y, m = cur.year, cur.month + months
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        nxt = date(y, m, 1)
        chunk_end = min(nxt - timedelta(days=1), final)
        out.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)

    return out


def _chunk_path(chunk_dir: Path, city_id: str, start: str, end: str) -> Path:
    return chunk_dir / f"{city_id}__{start}__{end}.parquet"


def _attach_metadata(df: pd.DataFrame, city) -> pd.DataFrame:
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["city_id"] = city.city_id
    df["latitude"] = float(city.latitude)
    df["longitude"] = float(city.longitude)
    df["elevation_m"] = int(city.elevation_m)
    df["data_source"] = "open-meteo"
    return df


def fetch_batch_chunk(
    batch: pd.DataFrame,
    start: str,
    end: str,
    chunk_dir: Path,
) -> tuple[int, list[dict]]:
    """Fetch one (city-batch, date-chunk) and write per-city parquet files.

    Returns (n_written, failures).
    """
    lats = batch["latitude"].tolist()
    lons = batch["longitude"].tolist()

    aq_blocks = fetch_archive_batch("air_quality", lats, lons, start, end)
    polite_pause()
    wx_blocks = fetch_archive_batch("weather", lats, lons, start, end)
    polite_pause()

    written = 0
    failures: list[dict] = []

    for i, city in enumerate(batch.itertuples(index=False)):
        aq = aq_blocks[i]
        wx = wx_blocks[i]

        if aq.empty and wx.empty:
            failures.append(
                {
                    "city_id": city.city_id,
                    "start": start,
                    "end": end,
                    "error": "empty response for both sources",
                }
            )
            continue

        if aq.empty:
            merged = wx
        elif wx.empty:
            merged = aq
        else:
            merged = aq.merge(wx, on="timestamp", how="outer")

        merged = _attach_metadata(merged, city)
        merged.to_parquet(
            _chunk_path(chunk_dir, city.city_id, start, end), index=False
        )
        written += 1

    return written, failures


def backfill(
    limit: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Download history for all cities. Returns an ingestion report."""
    cities = load_cities()
    if limit:
        cities = cities.nlargest(limit, "population").reset_index(drop=True)

    start = start_date or _TIME["air_quality_start"]
    end = end_date or (
        datetime.now(timezone.utc).date() - timedelta(days=1)
    ).isoformat()

    chunk_dir = resolve(_PATHS["raw_chunks"])
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunks = _month_chunks(start, end, int(_FETCH["chunk_months"]))
    batch_size = int(_FETCH["batch_size"])
    resume = bool(_FETCH["resume"])

    batches = [
        cities.iloc[i : i + batch_size] for i in range(0, len(cities), batch_size)
    ]

    log.info(
        "Backfill: %d cities in %d batches x %d chunks = %d requests "
        "(%s -> %s)",
        len(cities),
        len(batches),
        len(chunks),
        len(batches) * len(chunks) * 2,
        start,
        end,
    )

    downloaded = skipped = failed = 0
    failures: list[dict] = []
    unit = 0
    total_units = len(batches) * len(chunks)

    for bi, batch in enumerate(batches, start=1):
        for start_c, end_c in chunks:
            unit += 1

            # Only request the cities in this batch that are missing.
            if resume:
                missing = batch[
                    ~batch["city_id"].map(
                        lambda cid: _chunk_path(
                            chunk_dir, cid, start_c, end_c
                        ).exists()
                    )
                ]
            else:
                missing = batch

            if missing.empty:
                skipped += len(batch)
                continue

            try:
                n, fails = fetch_batch_chunk(missing, start_c, end_c, chunk_dir)
                downloaded += n
                failed += len(fails)
                failures.extend(fails)
            except OpenMeteoError as exc:
                failed += len(missing)
                failures.append(
                    {
                        "cities": missing["city_id"].tolist(),
                        "start": start_c,
                        "end": end_c,
                        "error": str(exc)[:200],
                    }
                )
                log.error(
                    "Batch %d/%d failed (%s..%s): %s",
                    bi,
                    len(batches),
                    start_c,
                    end_c,
                    exc,
                )

            log.info(
                "[%3d/%3d] batch %2d/%2d %s..%s  downloaded=%d skipped=%d failed=%d",
                unit,
                total_units,
                bi,
                len(batches),
                start_c,
                end_c,
                downloaded,
                skipped,
                failed,
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cities": int(len(cities)),
        "batch_size": batch_size,
        "chunks_per_city": len(chunks),
        "date_range": {"start": start, "end": end},
        "city_chunks_downloaded": downloaded,
        "city_chunks_skipped": skipped,
        "city_chunks_failed": failed,
        "failures": failures[:50],
        "api_stats": STATS.as_dict(),
    }


def combine_chunks() -> pd.DataFrame:
    """Merge every chunk parquet into the single combined dataset."""
    chunk_dir = resolve(_PATHS["raw_chunks"])
    files = sorted(chunk_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"No chunk files in {chunk_dir}. Run the backfill first."
        )

    log.info("Combining %d chunk files...", len(files))
    frames = []
    for i, fp in enumerate(files, start=1):
        try:
            frames.append(pd.read_parquet(fp))
        except Exception as exc:  # noqa: BLE001 - report and continue
            log.error("Unreadable chunk %s: %s", fp.name, exc)
        if i % 200 == 0:
            log.info("  read %d/%d", i, len(files))

    df = pd.concat(frames, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Normalise the schema to exactly what the config requests.
    #
    # Chunks downloaded at different times can carry different columns
    # (we trimmed the weather variable list to halve API cost). Mixing
    # them would hand the model a feature that is populated for one
    # slice of history and null for the rest — which looks like signal
    # and is really an artefact of when we hit the API.
    expected = [
        "timestamp",
        "city_id",
        "latitude",
        "longitude",
        "elevation_m",
        "data_source",
        *DATA_CFG["openmeteo_air_quality"]["variables"],
        *DATA_CFG["openmeteo_weather"]["variables"],
    ]
    dropped = [c for c in df.columns if c not in expected]
    if dropped:
        log.info("Dropping columns not in the current config: %s", dropped)
        df = df.drop(columns=dropped)
    for col in expected:
        if col not in df.columns:
            log.warning("Expected column missing from all chunks: %s", col)
            df[col] = pd.NA
    df = df[expected]

    # CAMS reanalysis occasionally emits tiny negative concentrations
    # (observed range -11 to -0.2 ug/m3). A negative mass concentration
    # is physically impossible, so clamp to zero. We log the count
    # rather than clamping silently: an unexplained jump in this number
    # would mean the upstream product changed.
    pollutants = [
        c for c in DATA_CFG["openmeteo_air_quality"]["variables"] if c in df.columns
    ]
    clamped = {}
    for col in pollutants:
        n = int((df[col] < 0).sum())
        if n:
            clamped[col] = n
            df[col] = df[col].clip(lower=0)
    if clamped:
        log.info("Clamped negative concentrations to zero: %s", clamped)

    before = len(df)
    df = df.drop_duplicates(subset=["city_id", "timestamp"], keep="last")
    df = df.sort_values(["city_id", "timestamp"]).reset_index(drop=True)
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")

    # float32 halves the file size; far more precision than ug/m3 needs.
    for col in df.select_dtypes(include=["float64"]).columns:
        if col not in {"latitude", "longitude"}:
            df[col] = df[col].astype("float32")

    log.info(
        "Combined: %d rows (%d duplicates dropped), %d cities, %s -> %s",
        len(df),
        before - len(df),
        df.city_id.nunique(),
        df.timestamp.min(),
        df.timestamp.max(),
    )

    out = resolve(_PATHS["raw_combined"])
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, compression="snappy")
    log.info("Wrote %s (%.1f MB)", out, out.stat().st_size / 1e6)
    return df


def _write_report(report: dict) -> None:
    path = resolve("reports/ingestion_report.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Ingestion report -> %s", path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill Pakistan air-quality history")
    ap.add_argument("--limit", type=int, help="only the N largest cities")
    ap.add_argument("--start", type=str, help="override start date (YYYY-MM-DD)")
    ap.add_argument("--end", type=str, help="override end date (YYYY-MM-DD)")
    ap.add_argument(
        "--combine-only",
        action="store_true",
        help="skip downloading, just rebuild the combined parquet",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.combine_only:
        report = backfill(limit=args.limit, start_date=args.start, end_date=args.end)
        _write_report(report)
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "failures"}, indent=2
            )
        )

    df = combine_chunks()
    print(f"\nFinal dataset: {df.shape[0]:,} rows x {df.shape[1]} columns")
    print(f"Cities: {df.city_id.nunique()}")
    print(f"Range : {df.timestamp.min()} -> {df.timestamp.max()}")
    if "pm2_5" in df.columns:
        print(f"PM2.5 non-null: {df.pm2_5.notna().mean() * 100:.1f}%")


if __name__ == "__main__":
    main()
