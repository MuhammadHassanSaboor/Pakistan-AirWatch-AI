"""Step B — feature engineering and the chronological train/val/test split."""

from kfp import dsl
from kfp.dsl import Dataset, Input, Metrics, Output

from .common import BASE_IMAGE, DATA_PACKAGES


@dsl.component(base_image=BASE_IMAGE, packages_to_install=DATA_PACKAGES)
def engineer_features(
    raw_dataset: Input[Dataset],
    train_set: Output[Dataset],
    val_set: Output[Dataset],
    test_set: Output[Dataset],
    stats: Output[Metrics],
    train_end: str = "2025-05-31T23:00:00Z",
    val_end: str = "2025-12-31T23:00:00Z",
    horizons: str = "1,6,12,24",
):
    """Lags, calendar and weather features, then a chronological split."""
    import numpy as np
    import pandas as pd

    df = pd.read_parquet(raw_dataset.path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(["city_id", "timestamp"]).reset_index(drop=True)

    # Calendar
    ts = df["timestamp"]
    df["hour"] = ts.dt.hour
    df["day_of_week"] = ts.dt.dayofweek
    df["month"] = ts.dt.month
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["is_smog_season"] = df["month"].isin([10, 11, 12, 1]).astype(int)

    # Lags — past information only.
    grouped = df.groupby("city_id", sort=False)["pm2_5"]
    for lag in (1, 3, 6, 12, 24, 48, 168):
        df[f"pm2_5_lag_{lag}h"] = grouped.shift(lag)
    shifted = grouped.shift(1)
    for window in (6, 24, 72):
        df[f"pm2_5_roll{window}_mean"] = (
            shifted.groupby(df["city_id"], sort=False)
            .rolling(window, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )

    if {"wind_speed_10m", "boundary_layer_height"} <= set(df.columns):
        df["ventilation_index"] = df["wind_speed_10m"] * df[
            "boundary_layer_height"
        ].fillna(500)

    # Supervised reshape
    frames = []
    for h in [int(x) for x in horizons.split(",")]:
        part = df.copy()
        part["horizon"] = h
        part["y"] = part.groupby("city_id", sort=False)["pm2_5"].shift(-h)
        frames.append(part)
    out = pd.concat(frames, ignore_index=True).dropna(subset=["y"])
    out = out.dropna(subset=["pm2_5_lag_1h"])

    # Chronological split
    stamps = pd.to_datetime(out["timestamp"], utc=True)
    train = out[stamps <= pd.Timestamp(train_end)]
    val = out[(stamps > pd.Timestamp(train_end)) & (stamps <= pd.Timestamp(val_end))]
    test = out[stamps > pd.Timestamp(val_end)]

    train.to_parquet(train_set.path, index=False)
    val.to_parquet(val_set.path, index=False)
    test.to_parquet(test_set.path, index=False)

    stats.log_metric("train_rows", float(len(train)))
    stats.log_metric("val_rows", float(len(val)))
    stats.log_metric("test_rows", float(len(test)))
    print(f"train={len(train):,} val={len(val):,} test={len(test):,}")
