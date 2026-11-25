"""Feast feature views.

Why a feature store at all
--------------------------
During training, `pm2_5_lag_24h` is computed with pandas in
`src/features/preprocessing.py`. During serving it has to be computed
again, from live data, in a different code path. If those two ever
disagree — a different fill value, a different timezone, a different
rolling window convention — the model silently receives inputs it was
never trained on. That failure is invisible in every metric: latency
is fine, the API returns 200, and the predictions are wrong.

Feast fixes this by making the feature definition the single source of
truth: training reads it from the offline store, serving reads the
same definition from the online store.

Each field below documents its source, transformation and freshness
expectation, as the specification requires.
"""

from datetime import timedelta

from entities import city
from feast import FeatureView, Field, FileSource
from feast.types import Float32, Int64, String

# ──────────────────────────────────────────────────────────────
# Sources
# ──────────────────────────────────────────────────────────────
# Path is relative to this file's directory. The parquet is produced
# by `python -m src.features.build_features` and versioned with DVC,
# so the feature-repo commit and the dataset MD5 together pin an
# exact feature set (both are recorded on every MLflow run).
processed_source = FileSource(
    name="processed_features",
    path="../../data/processed/feast_features.parquet",
    timestamp_field="timestamp",
    description=(
        "Hourly engineered features at OBSERVATION grain: exactly one "
        "row per (city_id, timestamp). Produced by "
        "feature_store/materialize.py --prepare from the DVC "
        "`features` stage output."
    ),
)

cities_source = FileSource(
    name="city_reference",
    path="../../data/processed/city_static.parquet",
    timestamp_field="timestamp",
    description="Static per-city attributes: location, elevation, population.",
)


# ──────────────────────────────────────────────────────────────
# Feature views
# ──────────────────────────────────────────────────────────────
city_pollution_lags = FeatureView(
    name="city_pollution_lags",
    entities=[city],
    # 3 days: a lag feature older than this is useless for an hourly
    # forecast, and serving a stale one is worse than serving none.
    ttl=timedelta(days=3),
    schema=[
        Field(
            name="pm2_5_lag_1h",
            dtype=Float32,
            description="PM2.5 one hour before the prediction time (ug/m3).",
        ),
        Field(
            name="pm2_5_lag_24h",
            dtype=Float32,
            description="PM2.5 24 hours earlier; captures the daily cycle.",
        ),
        Field(
            name="pm2_5_lag_168h",
            dtype=Float32,
            description="PM2.5 one week earlier; captures the weekly cycle.",
        ),
        Field(
            name="pm2_5_roll24_mean",
            dtype=Float32,
            description="Mean PM2.5 over the previous 24h, excluding now.",
        ),
        Field(
            name="pm2_5_roll24_std",
            dtype=Float32,
            description="Volatility of PM2.5 over the previous 24h.",
        ),
        Field(
            name="pm2_5_roll72_mean",
            dtype=Float32,
            description="Mean PM2.5 over the previous 72h; the slow trend.",
        ),
        Field(
            name="pm2_5_diff_24h",
            dtype=Float32,
            description="Change versus 24h ago; positive means worsening.",
        ),
        Field(
            name="neighbour_pm25_lag1h",
            dtype=Float32,
            description=(
                "Mean PM2.5 of the 3 nearest cities one hour ago. "
                "Pollution advects between cities."
            ),
        ),
    ],
    source=processed_source,
    online=True,
    tags={
        "owner": "hassan",
        "freshness": "hourly",
        "upstream": "open-meteo-cams",
        "leakage_safe": "true",
    },
    description="Lagged pollution history. Past-only by construction.",
)


city_weather_hourly = FeatureView(
    name="city_weather_hourly",
    entities=[city],
    ttl=timedelta(days=3),
    schema=[
        Field(
            name="temperature_2m",
            dtype=Float32,
            description="Air temperature at 2 m (degrees C).",
        ),
        Field(
            name="relative_humidity_2m",
            dtype=Float32,
            description="Relative humidity at 2 m (%).",
        ),
        Field(
            name="wind_speed_10m",
            dtype=Float32,
            description="Wind speed at 10 m (km/h). Disperses pollution.",
        ),
        Field(
            name="wind_u",
            dtype=Float32,
            description="East-west wind component; avoids the 0/360 wrap.",
        ),
        Field(
            name="wind_v",
            dtype=Float32,
            description="North-south wind component.",
        ),
        Field(
            name="boundary_layer_height",
            dtype=Float32,
            description="Mixing-layer depth (m). A shallow layer traps smog.",
        ),
        Field(
            name="ventilation_index",
            dtype=Float32,
            description=(
                "wind_speed * boundary_layer_height. The strongest "
                "single physical predictor of dispersion."
            ),
        ),
        Field(
            name="precipitation",
            dtype=Float32,
            description="Hourly precipitation (mm). Washes out particulates.",
        ),
    ],
    source=processed_source,
    online=True,
    tags={
        "owner": "hassan",
        "freshness": "hourly",
        "upstream": "open-meteo-era5",
        # Weather is legitimately known ahead of time, so unlike the
        # pollution features these may be used at the target hour.
        "future_safe": "true",
    },
    description="Weather drivers. Available as a forecast, so usable at t+h.",
)


city_calendar = FeatureView(
    name="city_calendar",
    entities=[city],
    ttl=timedelta(days=3),
    schema=[
        Field(name="hour", dtype=Int64, description="Hour of day, 0-23 UTC."),
        Field(name="day_of_week", dtype=Int64, description="Monday = 0."),
        Field(name="month", dtype=Int64, description="Calendar month, 1-12."),
        Field(
            name="hour_sin",
            dtype=Float32,
            description="sin(2*pi*hour/24); makes 23:00 adjacent to 00:00.",
        ),
        Field(name="hour_cos", dtype=Float32, description="cos of hour angle."),
        Field(
            name="is_smog_season",
            dtype=Int64,
            description="1 during Oct-Jan, Pakistan's smog season.",
        ),
        Field(
            name="is_burning_window",
            dtype=Int64,
            description="1 from mid-Oct to Nov, the crop-residue burning peak.",
        ),
    ],
    source=processed_source,
    online=True,
    tags={"owner": "hassan", "freshness": "derived", "future_safe": "true"},
    description="Calendar and seasonal flags derived from the timestamp.",
)


city_static = FeatureView(
    name="city_static",
    entities=[city],
    # No TTL. Feast treats timedelta(0) as unlimited, which is the
    # correct semantics for attributes that never expire.
    #
    # This was originally 365 days, and it silently broke every
    # historical retrieval: the static rows carry a single 2020
    # timestamp, so against 2026 entity rows they were all "expired"
    # and the point-in-time join returned ZERO rows -- not nulls for
    # the static columns, but no rows at all. A TTL belongs on data
    # that goes stale, not on a city's latitude.
    ttl=timedelta(seconds=0),
    schema=[
        Field(name="latitude", dtype=Float32, description="Decimal degrees N."),
        Field(name="longitude", dtype=Float32, description="Decimal degrees E."),
        Field(
            name="elevation_m",
            dtype=Float32,
            description="Metres above sea level; affects mixing and pressure.",
        ),
        Field(
            name="log_population",
            dtype=Float32,
            description="log1p(population); a proxy for emission density.",
        ),
        Field(name="province", dtype=String, description="Administrative unit."),
    ],
    source=cities_source,
    online=True,
    tags={"owner": "hassan", "freshness": "static", "source": "geonames"},
    description="Per-city constants that let one global model separate places.",
)
