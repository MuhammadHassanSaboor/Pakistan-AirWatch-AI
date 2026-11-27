"""Step A — schema and completeness checks on the raw dataset."""

from kfp import dsl
from kfp.dsl import Dataset, Input, Metrics, Output

from .common import BASE_IMAGE, DATA_PACKAGES


@dsl.component(base_image=BASE_IMAGE, packages_to_install=DATA_PACKAGES)
def validate_data(
    raw_dataset: Input[Dataset],
    report: Output[Metrics],
    min_rows: int = 10000,
) -> bool:
    """Schema and completeness checks. Returns False to halt the graph."""
    import pandas as pd

    df = pd.read_parquet(raw_dataset.path)

    checks = {
        "has_minimum_rows": len(df) >= min_rows,
        "has_target": "pm2_5" in df.columns,
        "no_duplicate_keys": not df.duplicated(["city_id", "timestamp"]).any(),
        "target_mostly_present": df["pm2_5"].isna().mean() < 0.30
        if "pm2_5" in df.columns
        else False,
        "coords_in_pakistan": bool(
            df["latitude"].between(23.0, 37.5).all()
            and df["longitude"].between(60.0, 78.0).all()
        )
        if {"latitude", "longitude"} <= set(df.columns)
        else False,
    }

    for name, passed in checks.items():
        report.log_metric(name, 1.0 if passed else 0.0)
    report.log_metric("rows", float(len(df)))
    report.log_metric("cities", float(df["city_id"].nunique()))

    ok = all(checks.values())
    print(f"Validation checks: {checks}")
    print(f"Overall: {'PASS' if ok else 'FAIL'}")
    return ok
