"""DVC pipeline stage: raw observations -> model-ready feature table.

Run
---
    python -m src.features.build_features
    python -m src.features.build_features --sample-cities 10   # fast dev loop
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime

import pandas as pd

from src.config import DATA_CFG, MODEL_CFG, resolve
from src.data.cities import load_cities
from src.features.preprocessing import build_features, feature_columns

log = logging.getLogger(__name__)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the feature table")
    ap.add_argument("--input", default=DATA_CFG["paths"]["raw_combined"])
    ap.add_argument("--output", default=DATA_CFG["paths"]["processed"])
    ap.add_argument(
        "--sample-cities",
        type=int,
        help="only use N cities (fast iteration during development)",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    src = resolve(args.input)
    log.info("Reading %s", src)
    raw = pd.read_parquet(src)
    cities = load_cities()

    if args.sample_cities:
        keep = cities.nlargest(args.sample_cities, "population")["city_id"].tolist()
        raw = raw[raw["city_id"].isin(keep)]
        log.info("Sampling %d cities", len(keep))

    log.info("Raw: %d rows, %d cities", len(raw), raw.city_id.nunique())

    features = build_features(raw, cities=cities)
    cols = feature_columns(features)

    log.info(
        "Features: %d rows x %d model columns (%d total columns)",
        len(features),
        len(cols),
        features.shape[1],
    )

    out = resolve(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(out, index=False, compression="snappy")
    log.info("Wrote %s (%.1f MB)", out, out.stat().st_size / 1e6)

    # Machine-readable summary for DVC metrics and the report.
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "rows": int(len(features)),
        "cities": int(features.city_id.nunique()),
        "n_model_features": len(cols),
        "horizons": list(MODEL_CFG["horizons"]),
        "time_range": {
            "start": str(features.timestamp.min()),
            "end": str(features.timestamp.max()),
        },
        "target_stats": {
            "mean": round(float(features.y.mean()), 3),
            "std": round(float(features.y.std()), 3),
            "p50": round(float(features.y.quantile(0.5)), 3),
            "p95": round(float(features.y.quantile(0.95)), 3),
            "max": round(float(features.y.max()), 3),
        },
        "feature_names": cols,
    }
    report = resolve("reports/feature_summary.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nFeature table: {len(features):,} rows x {len(cols)} model features")
    print(f"Cities : {features.city_id.nunique()}")
    print(f"Range  : {features.timestamp.min()} -> {features.timestamp.max()}")
    print(f"Target y: mean={features.y.mean():.1f} p95={features.y.quantile(0.95):.1f}")
    print(f"\nSummary -> {report}")


if __name__ == "__main__":
    main()
