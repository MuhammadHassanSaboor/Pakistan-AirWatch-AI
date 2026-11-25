"""Feature engineering for hourly PM2.5 forecasting.

THE LEAKAGE RULE
----------------
To predict PM2.5 at time ``t + h`` we may use:
  * pollutant values at ``t`` and earlier  (lags, rolling stats)
  * weather at ``t + h``                   (a forecast is genuinely
                                            available ahead of time)
  * calendar and static location features

We may NEVER use the pollutant value at ``t + h`` itself, nor any
pollutant reading between ``t+1`` and ``t+h``. Breaking this rule
produces an R^2 near 0.99 and a model that cannot forecast anything.
``tests/test_features.py`` enforces it.

Every transformation here is grouped by ``city_id`` so one city's
history never bleeds into another's.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.config import MODEL_CFG

log = logging.getLogger(__name__)

_FEAT = MODEL_CFG["features"]
LAGS: list[int] = list(_FEAT["lags"])
ROLLING: list[int] = list(_FEAT["rolling_windows"])
TARGET: str = MODEL_CFG["target"]

# Pollutants that get lag treatment (all are "known only in the past").
POLLUTANTS = [
    "pm2_5",
    "pm10",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "dust",
]

# Weather is available as a forecast, so it may be used at t+h directly.
WEATHER = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation",
    "surface_pressure",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "boundary_layer_height",
    "shortwave_radiation",
]


# ──────────────────────────────────────────────────────────────
# Calendar
# ──────────────────────────────────────────────────────────────
def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Hour/day/month plus Pakistan-specific seasonal flags."""
    ts = pd.to_datetime(df["timestamp"], utc=True)

    df["hour"] = ts.dt.hour.astype("int16")
    df["day_of_week"] = ts.dt.dayofweek.astype("int16")
    df["day_of_year"] = ts.dt.dayofyear.astype("int16")
    df["month"] = ts.dt.month.astype("int16")
    df["year"] = ts.dt.year.astype("int16")
    df["is_weekend"] = (df["day_of_week"] >= 5).astype("int8")

    # Cyclical encoding: hour 23 and hour 0 must be neighbours, and
    # December must sit next to January. Raw integers cannot express that.
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24).astype("float32")
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24).astype("float32")
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12).astype("float32")
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12).astype("float32")
    df["doy_sin"] = np.sin(2 * np.pi * df["day_of_year"] / 365.25).astype("float32")
    df["doy_cos"] = np.cos(2 * np.pi * df["day_of_year"] / 365.25).astype("float32")

    # Domain knowledge: Pakistan's smog season dominates PM2.5 variance.
    df["is_smog_season"] = df["month"].isin([10, 11, 12, 1]).astype("int8")
    df["is_monsoon"] = df["month"].isin([7, 8, 9]).astype("int8")
    df["is_summer"] = df["month"].isin([4, 5, 6]).astype("int8")

    # Crop-residue burning peaks in late Oct / early Nov across Punjab.
    df["is_burning_window"] = (
        ((df["month"] == 10) & (ts.dt.day >= 15)) | (df["month"] == 11)
    ).astype("int8")

    # Rush hours drive local traffic emissions.
    df["is_rush_hour"] = df["hour"].isin([7, 8, 9, 17, 18, 19]).astype("int8")
    df["is_night"] = ((df["hour"] >= 22) | (df["hour"] <= 5)).astype("int8")

    return df


# ──────────────────────────────────────────────────────────────
# Lags and rolling statistics  (past information only)
# ──────────────────────────────────────────────────────────────
def add_lag_features(
    df: pd.DataFrame,
    target: str = TARGET,
    lags: list[int] | None = None,
    rolling: list[int] | None = None,
) -> pd.DataFrame:
    """Lagged and rolling pollutant history, grouped per city.

    Rolling windows are computed on ``shift(1)`` so the current hour
    never contributes to its own rolling mean.
    """
    lags = lags or LAGS
    rolling = rolling or ROLLING
    g = df.groupby("city_id", sort=False)[target]

    for lag in lags:
        df[f"{target}_lag_{lag}h"] = g.shift(lag).astype("float32")

    shifted = g.shift(1)
    grouped_shift = shifted.groupby(df["city_id"], sort=False)
    for window in rolling:
        roll = grouped_shift.rolling(window, min_periods=1)
        df[f"{target}_roll{window}_mean"] = (
            roll.mean().reset_index(level=0, drop=True).astype("float32")
        )
        df[f"{target}_roll{window}_std"] = (
            roll.std().reset_index(level=0, drop=True).astype("float32")
        )
        df[f"{target}_roll{window}_max"] = (
            roll.max().reset_index(level=0, drop=True).astype("float32")
        )
        df[f"{target}_roll{window}_min"] = (
            roll.min().reset_index(level=0, drop=True).astype("float32")
        )

    # Momentum: is pollution rising or falling?
    df[f"{target}_diff_1h"] = (df[f"{target}_lag_1h"] - df[f"{target}_lag_2h"]).astype(
        "float32"
    )
    df[f"{target}_diff_24h"] = (
        df[f"{target}_lag_1h"] - df[f"{target}_lag_24h"]
    ).astype("float32")
    if f"{target}_roll24_mean" in df and f"{target}_roll72_mean" in df:
        df[f"{target}_ratio_24_72"] = (
            df[f"{target}_roll24_mean"] / (df[f"{target}_roll72_mean"] + 1e-6)
        ).astype("float32")

    # Short lags for the other pollutants — they co-vary with PM2.5.
    for pol in POLLUTANTS:
        if pol == target or pol not in df.columns:
            continue
        gp = df.groupby("city_id", sort=False)[pol]
        for lag in (1, 24):
            df[f"{pol}_lag_{lag}h"] = gp.shift(lag).astype("float32")

    return df


# ──────────────────────────────────────────────────────────────
# Weather-derived features
# ──────────────────────────────────────────────────────────────
def add_weather_features(df: pd.DataFrame) -> pd.DataFrame:
    """Physically meaningful combinations of weather variables."""
    if {"wind_speed_10m", "wind_direction_10m"} <= set(df.columns):
        rad = np.deg2rad(df["wind_direction_10m"].astype("float32"))
        speed = df["wind_speed_10m"].astype("float32")
        # Direction is circular; 359 deg and 1 deg are nearly identical.
        # Decomposing into u/v components removes the discontinuity.
        df["wind_u"] = (-speed * np.sin(rad)).astype("float32")
        df["wind_v"] = (-speed * np.cos(rad)).astype("float32")
        df["is_calm"] = (speed < 2.0).astype("int8")

    # Ventilation index = wind speed x mixing height. The single best
    # physical predictor of how fast pollution disperses.
    if {"wind_speed_10m", "boundary_layer_height"} <= set(df.columns):
        df["ventilation_index"] = (
            df["wind_speed_10m"].astype("float32")
            * df["boundary_layer_height"].astype("float32").fillna(500.0)
        ).astype("float32")
        df["log_ventilation"] = np.log1p(df["ventilation_index"].clip(lower=0)).astype(
            "float32"
        )

    # A shallow boundary layer traps pollution near the ground.
    if "boundary_layer_height" in df.columns:
        df["is_shallow_blh"] = (df["boundary_layer_height"] < 300).astype("int8")

    if {"temperature_2m", "relative_humidity_2m"} <= set(df.columns):
        df["temp_humidity"] = (
            df["temperature_2m"].astype("float32")
            * df["relative_humidity_2m"].astype("float32")
            / 100.0
        ).astype("float32")

    # Rain washes particulates out of the air.
    if "precipitation" in df.columns:
        df["is_raining"] = (df["precipitation"] > 0.1).astype("int8")
        g = df.groupby("city_id", sort=False)["precipitation"]
        df["precip_roll24_sum"] = (
            g.shift(1)
            .groupby(df["city_id"], sort=False)
            .rolling(24, min_periods=1)
            .sum()
            .reset_index(level=0, drop=True)
            .astype("float32")
        )

    # Temperature inversions concentrate smog; proxy via day-night swing.
    if "temperature_2m" in df.columns:
        g = df.groupby("city_id", sort=False)["temperature_2m"]
        df["temp_diff_24h"] = (df["temperature_2m"] - g.shift(24)).astype("float32")

    return df


# ──────────────────────────────────────────────────────────────
# Spatial features
# ──────────────────────────────────────────────────────────────
def add_spatial_features(
    df: pd.DataFrame, n_neighbours: int | None = None
) -> pd.DataFrame:
    """Lagged pollution of the nearest cities — pollution travels.

    Uses ``pm2_5_lag_1h`` (already past-only) so no leakage is
    introduced: at prediction time every neighbour value is known.
    """
    n_neighbours = n_neighbours or int(_FEAT["n_spatial_neighbours"])
    lag_col = f"{TARGET}_lag_1h"
    if lag_col not in df.columns:
        log.warning("Skipping spatial features: %s missing", lag_col)
        return df

    coords = df.groupby("city_id")[["latitude", "longitude"]].first().sort_index()
    ids = coords.index.to_numpy()

    # Equirectangular approximation — accurate enough at Pakistan's scale
    # and far cheaper than haversine for a 130x130 matrix.
    lat = np.deg2rad(coords["latitude"].to_numpy())
    lon = np.deg2rad(coords["longitude"].to_numpy())
    mean_lat = lat.mean()
    x = lon * np.cos(mean_lat) * 6371.0
    y = lat * 6371.0
    dist = np.sqrt((x[:, None] - x[None, :]) ** 2 + (y[:, None] - y[None, :]) ** 2)
    np.fill_diagonal(dist, np.inf)

    neighbours = {
        ids[i]: ids[np.argsort(dist[i])[:n_neighbours]].tolist()
        for i in range(len(ids))
    }

    # Pivot to a (timestamp x city) matrix so neighbour lookup is vectorised.
    wide = df.pivot_table(
        index="timestamp", columns="city_id", values=lag_col, aggfunc="first"
    )

    neighbour_mean = pd.DataFrame(index=wide.index)
    for city, neigh in neighbours.items():
        present = [n for n in neigh if n in wide.columns]
        neighbour_mean[city] = wide[present].mean(axis=1) if present else np.nan

    long = (
        neighbour_mean.stack(future_stack=True)
        .rename("neighbour_pm25_lag1h")
        .reset_index()
    )
    long.columns = ["timestamp", "city_id", "neighbour_pm25_lag1h"]

    df = df.merge(long, on=["timestamp", "city_id"], how="left")
    df["neighbour_pm25_lag1h"] = df["neighbour_pm25_lag1h"].astype("float32")
    df["neighbour_diff"] = (df[lag_col] - df["neighbour_pm25_lag1h"]).astype("float32")

    return df


def add_static_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-city constants the model can use to distinguish locations."""
    for col in ("latitude", "longitude", "elevation_m"):
        if col in df.columns:
            df[col] = df[col].astype("float32")

    if "population" in df.columns:
        df["log_population"] = np.log1p(df["population"].astype("float32")).astype(
            "float32"
        )
    if "elevation_m" in df.columns:
        df["is_highland"] = (df["elevation_m"] > 1000).astype("int8")
    return df


# ──────────────────────────────────────────────────────────────
# Supervised reshaping
# ──────────────────────────────────────────────────────────────
def make_supervised(
    df: pd.DataFrame,
    horizons: list[int],
    target: str = TARGET,
) -> pd.DataFrame:
    """Long format: one row per (city, time, horizon), label column ``y``.

    ``y`` is the target shifted BACKWARD by h, i.e. the future value we
    are trying to predict. ``horizon`` becomes an ordinary feature, so
    a single model serves every lead time.
    """
    frames = []
    for h in horizons:
        part = df.copy()
        part["horizon"] = np.int16(h)
        part["y"] = (
            part.groupby("city_id", sort=False)[target].shift(-h).astype("float32")
        )
        # The timestamp the prediction is FOR (used by the API and UI).
        part["valid_time"] = part["timestamp"] + pd.to_timedelta(h, unit="h")
        frames.append(part)

    out = pd.concat(frames, ignore_index=True)
    before = len(out)
    out = out.dropna(subset=["y"])
    log.info(
        "Supervised reshape: %d rows (%d dropped for missing label)",
        len(out),
        before - len(out),
    )
    return out


# ──────────────────────────────────────────────────────────────
# Pipeline entry point
# ──────────────────────────────────────────────────────────────
def build_features(
    raw: pd.DataFrame,
    cities: pd.DataFrame | None = None,
    horizons: list[int] | None = None,
    target: str = TARGET,
) -> pd.DataFrame:
    """Raw hourly observations -> model-ready supervised table."""
    horizons = horizons or list(MODEL_CFG["horizons"])

    df = raw.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(["city_id", "timestamp"]).reset_index(drop=True)

    if cities is not None:
        extra = [
            c
            for c in ("city_name", "province", "population")
            if c in cities.columns and c not in df.columns
        ]
        if extra:
            df = df.merge(cities[["city_id", *extra]], on="city_id", how="left")

    log.info("Building calendar features...")
    df = add_calendar_features(df)

    log.info("Building lag features...")
    df = add_lag_features(df, target=target)

    log.info("Building weather features...")
    df = add_weather_features(df)

    log.info("Building spatial features...")
    df = add_spatial_features(df)

    df = add_static_features(df)

    log.info("Reshaping to supervised format for horizons %s...", horizons)
    df = make_supervised(df, horizons=horizons, target=target)

    # Rows with no recent history cannot be predicted from.
    essential = [f"{target}_lag_1h", f"{target}_lag_24h"]
    present = [c for c in essential if c in df.columns]
    if present:
        before = len(df)
        df = df.dropna(subset=present)
        log.info("Dropped %d rows lacking essential lags", before - len(df))

    return df.reset_index(drop=True)


def feature_columns(df: pd.DataFrame, exclude: list[str] | None = None) -> list[str]:
    """Numeric columns the model may train on.

    Excludes identifiers, timestamps and the label. Centralised so the
    training scripts and the serving code agree exactly.
    """
    exclude = set(exclude or _FEAT["exclude"])
    exclude |= {"valid_time", "y"}
    return [
        c
        for c in df.columns
        if c not in exclude and pd.api.types.is_numeric_dtype(df[c])
    ]


__all__ = [
    "LAGS",
    "ROLLING",
    "TARGET",
    "add_calendar_features",
    "add_lag_features",
    "add_weather_features",
    "add_spatial_features",
    "add_static_features",
    "make_supervised",
    "build_features",
    "feature_columns",
]
