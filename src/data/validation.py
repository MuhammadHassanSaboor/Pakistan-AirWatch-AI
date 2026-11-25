"""Data validation and quality checks.

Two layers:

1. **Schema validation** (Pandera) — types, ranges, nullability.
   Catches structural problems: a renamed column, a unit change
   upstream, coordinates outside Pakistan.
2. **Quality rules** — business logic a schema cannot express:
   freshness, completeness per city, physical consistency
   (PM2.5 <= PM10), flatlined sensors, duplicate timestamps.

Both return a report instead of raising, because Airflow needs to
record *why* a run failed, and because a partial dataset is often
still usable. The caller decides whether to stop.

Run
---
    python -m src.data.validation --input data/raw/airquality_hourly.parquet
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

# pandera moved the pandas API into a submodule in 0.21. Support both
# so the project works across the versions a team member might install.
try:  # pandera >= 0.21
    import pandera.pandas as pa
    from pandera.pandas import Check, Column, DataFrameSchema
except ImportError:  # pandera < 0.21
    import pandera as pa
    from pandera import Check, Column, DataFrameSchema

from src.config import DATA_CFG, resolve

log = logging.getLogger(__name__)

_BBOX = DATA_CFG["cities"]["bbox"]

# Physically plausible ranges. Generous on purpose: the job of this
# schema is to catch unit errors and corruption, NOT to reject genuine
# extreme events.
#
# The upper bounds were set after inspecting the empirical
# distribution, not guessed. Two findings drove them:
#   * Lahore routinely exceeds 500 ug/m3 PM2.5 in winter smog season.
#   * Nushki (Balochistan), 19-23 March 2024, recorded dust at
#     10,134 ug/m3 with PM10 at 3,181 — a real dust storm. An earlier
#     5,000 cap on dust rejected it. Those are exactly the events a
#     forecasting system exists to predict, so the bound moved rather
#     than the data.
RAW_SCHEMA = DataFrameSchema(
    columns={
        "city_id": Column(str, nullable=False),
        "timestamp": Column("datetime64[ns, UTC]", nullable=False),
        "latitude": Column(
            float, Check.in_range(_BBOX["lat_min"], _BBOX["lat_max"]), nullable=False
        ),
        "longitude": Column(
            float, Check.in_range(_BBOX["lon_min"], _BBOX["lon_max"]), nullable=False
        ),
        "pm2_5": Column(float, Check.in_range(0, 2000), nullable=True, required=False),
        "pm10": Column(float, Check.in_range(0, 6000), nullable=True, required=False),
        "carbon_monoxide": Column(
            float, Check.in_range(0, 20000), nullable=True, required=False
        ),
        "nitrogen_dioxide": Column(
            float, Check.in_range(0, 1000), nullable=True, required=False
        ),
        "sulphur_dioxide": Column(
            float, Check.in_range(0, 1000), nullable=True, required=False
        ),
        "ozone": Column(float, Check.in_range(0, 1000), nullable=True, required=False),
        "dust": Column(float, Check.in_range(0, 20000), nullable=True, required=False),
        "temperature_2m": Column(
            float, Check.in_range(-30, 60), nullable=True, required=False
        ),
        "relative_humidity_2m": Column(
            float, Check.in_range(0, 100), nullable=True, required=False
        ),
        "surface_pressure": Column(
            float, Check.in_range(500, 1100), nullable=True, required=False
        ),
        "wind_speed_10m": Column(
            float, Check.in_range(0, 200), nullable=True, required=False
        ),
        "wind_direction_10m": Column(
            float, Check.in_range(0, 360), nullable=True, required=False
        ),
        "boundary_layer_height": Column(
            float, Check.in_range(0, 10000), nullable=True, required=False
        ),
        "precipitation": Column(
            float, Check.in_range(0, 500), nullable=True, required=False
        ),
    },
    strict=False,      # extra columns are allowed
    coerce=True,
    ordered=False,
)


def validate_schema(df: pd.DataFrame) -> tuple[bool, dict[str, Any]]:
    """Run the Pandera schema. Never raises."""
    try:
        RAW_SCHEMA.validate(df, lazy=True)
        return True, {"status": "pass", "rows": int(len(df)), "failures": []}
    except pa.errors.SchemaErrors as exc:
        cases = exc.failure_cases
        summary = (
            cases.groupby(["column", "check"])
            .size()
            .reset_index(name="count")
            .to_dict("records")
        )
        return False, {
            "status": "fail",
            "rows": int(len(df)),
            "n_failure_cases": int(len(cases)),
            "failures": summary[:50],
        }


def check_quality(df: pd.DataFrame, target: str = "pm2_5") -> dict[str, Any]:
    """Business-rule checks that a schema cannot express."""
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: Any = None) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    # 1. No duplicate (city, timestamp) pairs.
    n_dupes = int(df.duplicated(subset=["city_id", "timestamp"]).sum())
    record("no_duplicate_city_timestamp", n_dupes == 0, {"duplicates": n_dupes})

    # 2. Target completeness.
    if target in df.columns:
        missing = float(df[target].isna().mean())
        record(
            "target_completeness",
            missing < 0.30,
            {"missing_fraction": round(missing, 4), "threshold": 0.30},
        )
    else:
        record("target_completeness", False, {"error": f"{target} column absent"})

    # 3. Freshness — newest record should be recent.
    newest = df["timestamp"].max()
    age_h = (pd.Timestamp.now(tz="UTC") - newest).total_seconds() / 3600
    record(
        "data_freshness",
        age_h < 72,
        {"newest": str(newest), "age_hours": round(age_h, 1), "threshold_hours": 72},
    )

    # 4. Physical consistency: fine particles are a subset of coarse.
    if {"pm2_5", "pm10"} <= set(df.columns):
        both = df[["pm2_5", "pm10"]].dropna()
        violations = int((both["pm2_5"] > both["pm10"] * 1.05).sum())
        frac = violations / max(len(both), 1)
        record(
            "pm25_not_above_pm10",
            frac < 0.02,
            {"violations": violations, "fraction": round(frac, 5)},
        )

    # 5. Per-city coverage — every city should have a usable series.
    if target in df.columns:
        per_city = df.groupby("city_id")[target].apply(lambda s: s.notna().mean())
        poor = per_city[per_city < 0.50]
        record(
            "per_city_coverage",
            poor.empty,
            {
                "cities_below_50pct": int(len(poor)),
                "worst": poor.nsmallest(5).round(3).to_dict(),
            },
        )

    # 6. Flatline detection — a stuck sensor repeats one value forever.
    #    Threshold is 36h, not 12h: reanalysis over clean, remote
    #    highlands (Quetta, Skardu, Chilas) legitimately holds a
    #    constant low value overnight, and 12h flagged all of them.
    if target in df.columns:
        def _max_flat_run(s: pd.Series) -> int:
            v = s.dropna()
            if v.empty:
                return 0
            grp = (v != v.shift()).cumsum()
            return int(v.groupby(grp).size().max())

        runs = df.groupby("city_id")[target].apply(_max_flat_run)
        flat = runs[runs > 36]
        record(
            "no_long_flatlines",
            flat.empty,
            {"cities_with_flatline": int(len(flat)), "worst": flat.nlargest(5).to_dict()},
        )

    # 7. Outlier census — flagged, never silently dropped.
    if target in df.columns:
        extreme = int((df[target] > 1000).sum())
        record(
            "extreme_value_census",
            True,  # informational
            {"values_above_1000": extreme, "note": "flagged, not removed"},
        )

    passed = all(c["passed"] for c in checks)
    return {
        "status": "pass" if passed else "fail",
        "n_checks": len(checks),
        "n_failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }


def validate_raw(
    df: pd.DataFrame, target: str = "pm2_5"
) -> tuple[bool, dict[str, Any]]:
    """Full validation: schema + quality rules. Never raises.

    Returns (ok, report). `ok` is False if EITHER layer failed.
    """
    schema_ok, schema_report = validate_schema(df)
    quality_report = check_quality(df, target=target)
    ok = schema_ok and quality_report["status"] == "pass"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": "pass" if ok else "fail",
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "cities": int(df["city_id"].nunique()) if "city_id" in df else 0,
        "time_range": {
            "start": str(df["timestamp"].min()) if "timestamp" in df else None,
            "end": str(df["timestamp"].max()) if "timestamp" in df else None,
        },
        "schema": schema_report,
        "quality": quality_report,
    }
    return ok, report


def profile(df: pd.DataFrame) -> dict[str, Any]:
    """Per-column summary, saved alongside the validation report."""
    out: dict[str, Any] = {}
    for col in df.select_dtypes("number").columns:
        s = df[col]
        out[col] = {
            "non_null": int(s.notna().sum()),
            "missing_pct": round(float(s.isna().mean() * 100), 2),
            "mean": round(float(s.mean()), 3) if s.notna().any() else None,
            "std": round(float(s.std()), 3) if s.notna().any() else None,
            "min": round(float(s.min()), 3) if s.notna().any() else None,
            "p50": round(float(s.quantile(0.50)), 3) if s.notna().any() else None,
            "p99": round(float(s.quantile(0.99)), 3) if s.notna().any() else None,
            "max": round(float(s.max()), 3) if s.notna().any() else None,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate the raw dataset")
    ap.add_argument(
        "--input", default=DATA_CFG["paths"]["raw_combined"], help="parquet to validate"
    )
    ap.add_argument("--output", default=DATA_CFG["paths"]["quality_report"])
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when validation fails (used by CI and Airflow)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    df = pd.read_parquet(resolve(args.input))
    ok, report = validate_raw(df)
    report["profile"] = profile(df)

    out = resolve(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"\nValidation: {report['overall_status'].upper()}")
    print(f"  rows   : {report['rows']:,}")
    print(f"  cities : {report['cities']}")
    print(f"  range  : {report['time_range']['start']} -> {report['time_range']['end']}")
    print(f"\n  schema : {report['schema']['status']}")
    for c in report["quality"]["checks"]:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"  [{mark}] {c['check']}: {c['detail']}")
    print(f"\nReport -> {out}")

    if args.strict and not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
