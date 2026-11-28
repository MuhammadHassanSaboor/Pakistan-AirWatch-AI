"""ETL load step: validated observations -> PostgreSQL warehouse.

    Extract   Open-Meteo (src/data/ingestion.py)  -> data/raw/*.parquet
    Transform schema + quality checks (src/data/validation.py)
    Load      THIS MODULE -> Postgres tables `cities`, `observations`,
              `etl_runs`

The load is an idempotent UPSERT keyed on (city_id, timestamp): running
it twice, or re-loading an overlapping window from the daily job, never
creates duplicates. Each run is recorded in `etl_runs` for auditability.

The warehouse is also the source for retraining: `extract_observations()`
reads it back so the daily retraining DAG trains on exactly what was
loaded.

    python -m src.data.load_db                       # load the combined raw parquet
    python -m src.data.load_db --source <file.parquet>
    python -m src.data.load_db --summary             # row counts and date range

Connection: DATABASE_URL, or POSTGRES_USER/PASSWORD/HOST/PORT/DB (see .env.example).
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from src.config import DATA_CFG, resolve, settings

log = logging.getLogger(__name__)

KEY = ["city_id", "timestamp"]

# Columns kept in the warehouse. Anything else in the parquet (derived or
# bookkeeping columns) stays out of the fact table.
OBS_COLUMNS = [
    "city_id",
    "timestamp",
    *DATA_CFG["openmeteo_air_quality"]["variables"],
    *DATA_CFG["openmeteo_weather"]["variables"],
]

CITY_COLUMNS = [
    "city_id",
    "city_name",
    "province",
    "latitude",
    "longitude",
    "elevation_m",
    "population",
]

DDL = [
    """
    CREATE TABLE IF NOT EXISTS cities (
        city_id      TEXT PRIMARY KEY,
        city_name    TEXT,
        province     TEXT,
        latitude     DOUBLE PRECISION NOT NULL,
        longitude    DOUBLE PRECISION NOT NULL,
        elevation_m  DOUBLE PRECISION,
        population   BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS etl_runs (
        run_id        SERIAL PRIMARY KEY,
        started_at    TIMESTAMPTZ NOT NULL,
        finished_at   TIMESTAMPTZ,
        source        TEXT,
        rows_in       INTEGER,
        rows_upserted INTEGER,
        min_ts        TIMESTAMPTZ,
        max_ts        TIMESTAMPTZ,
        status        TEXT
    )
    """,
]


def _obs_ddl(columns: list[str]) -> str:
    value_cols = [c for c in columns if c not in KEY]
    body = ",\n        ".join(f"{c} DOUBLE PRECISION" for c in value_cols)
    return f"""
    CREATE TABLE IF NOT EXISTS observations (
        city_id    TEXT NOT NULL REFERENCES cities(city_id),
        timestamp  TIMESTAMPTZ NOT NULL,
        {body},
        loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (city_id, timestamp)
    )
    """


def get_engine(url: str | None = None):
    from sqlalchemy import create_engine

    url = url or settings.database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, pool_pre_ping=True, future=True)


def ensure_schema(engine, columns: list[str] | None = None) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
        conn.execute(text(_obs_ddl(columns or OBS_COLUMNS)))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_observations_ts "
                "ON observations (timestamp)"
            )
        )


def prepare_observations(df: pd.DataFrame) -> pd.DataFrame:
    """Keep warehouse columns, normalise types, drop duplicate keys."""
    cols = [c for c in OBS_COLUMNS if c in df.columns]
    missing_key = [k for k in KEY if k not in df.columns]
    if missing_key:
        raise ValueError(f"Source is missing key columns: {missing_key}")
    out = df[cols].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    for c in cols:
        if c not in KEY:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
    return out.drop_duplicates(subset=KEY, keep="last").reset_index(drop=True)


def _upsert(conn, frame: pd.DataFrame, table: str, key: list[str]) -> int:
    """Stage into a temp table, then INSERT ... ON CONFLICT DO UPDATE."""
    from sqlalchemy import text

    stage = f"_stage_{table}"
    conn.execute(text(f"DROP TABLE IF EXISTS {stage}"))
    conn.execute(text(f"CREATE TEMP TABLE {stage} (LIKE {table} INCLUDING DEFAULTS)"))
    frame.to_sql(
        stage, conn, if_exists="append", index=False, method="multi", chunksize=5000
    )

    cols = list(frame.columns)
    col_list = ", ".join(cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in key)
    conflict = ", ".join(key)
    action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    result = conn.execute(
        text(
            f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {stage} "
            f"ON CONFLICT ({conflict}) {action}"
        )
    )
    conn.execute(text(f"DROP TABLE IF EXISTS {stage}"))
    return int(result.rowcount or 0)


def load_cities(engine, cities: pd.DataFrame) -> int:
    cols = [c for c in CITY_COLUMNS if c in cities.columns]
    with engine.begin() as conn:
        return _upsert(
            conn, cities[cols].drop_duplicates("city_id"), "cities", ["city_id"]
        )


def load_observations(
    df: pd.DataFrame,
    engine=None,
    source: str = "dataframe",
    batch_rows: int = 200_000,
) -> dict[str, Any]:
    """Upsert observations (and their cities) into the warehouse."""
    from sqlalchemy import text

    from src.data.cities import load_cities as read_city_table

    engine = engine or get_engine()
    obs = prepare_observations(df)
    ensure_schema(engine, list(obs.columns))

    started = datetime.now(UTC)
    with engine.begin() as conn:
        run_id = conn.execute(
            text(
                "INSERT INTO etl_runs (started_at, source, rows_in, status) "
                "VALUES (:s, :src, :n, 'running') RETURNING run_id"
            ),
            {"s": started, "src": source, "n": len(obs)},
        ).scalar_one()

    cities = read_city_table()
    cities = cities[cities["city_id"].isin(obs["city_id"].unique())]
    load_cities(engine, cities)

    upserted = 0
    t0 = time.time()
    for i in range(0, len(obs), batch_rows):
        part = obs.iloc[i : i + batch_rows]
        with engine.begin() as conn:
            upserted += _upsert(conn, part, "observations", KEY)
        log.info("Loaded %d/%d rows", min(i + batch_rows, len(obs)), len(obs))

    summary = {
        "run_id": run_id,
        "rows_in": len(obs),
        "rows_upserted": upserted,
        "cities": int(obs["city_id"].nunique()),
        "min_ts": obs["timestamp"].min(),
        "max_ts": obs["timestamp"].max(),
        "seconds": round(time.time() - t0, 1),
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE etl_runs SET finished_at=:f, rows_upserted=:u, "
                "min_ts=:lo, max_ts=:hi, status='success' WHERE run_id=:r"
            ),
            {
                "f": datetime.now(UTC),
                "u": upserted,
                "lo": summary["min_ts"],
                "hi": summary["max_ts"],
                "r": run_id,
            },
        )
    return summary


def latest_timestamp(engine=None) -> pd.Timestamp | None:
    """Most recent observation in the warehouse (for incremental fetches)."""
    from sqlalchemy import inspect, text

    engine = engine or get_engine()
    if not inspect(engine).has_table("observations"):
        return None
    with engine.connect() as conn:
        value = conn.execute(text("SELECT max(timestamp) FROM observations")).scalar()
    return pd.Timestamp(value) if value is not None else None


def extract_observations(engine=None, since: str | None = None) -> pd.DataFrame:
    """Read observations joined with city metadata — the training input."""
    from sqlalchemy import text

    engine = engine or get_engine()
    where = "WHERE o.timestamp >= :since" if since else ""
    sql = text(
        "SELECT o.*, c.city_name, c.province, c.latitude, c.longitude, "
        "c.elevation_m, c.population "
        f"FROM observations o JOIN cities c USING (city_id) {where} "
        "ORDER BY o.city_id, o.timestamp"
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"since": since} if since else {})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.drop(columns=["loaded_at"], errors="ignore")


def summary(engine=None) -> dict[str, Any]:
    from sqlalchemy import text

    engine = engine or get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT count(*), count(DISTINCT city_id), min(timestamp), "
                "max(timestamp) FROM observations"
            )
        ).one()
        runs = conn.execute(text("SELECT count(*) FROM etl_runs")).scalar()
    return {
        "observations": row[0],
        "cities": row[1],
        "from": str(row[2]),
        "to": str(row[3]),
        "etl_runs": runs,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Load observations into Postgres")
    ap.add_argument("--source", default=DATA_CFG["paths"]["raw_combined"])
    ap.add_argument("--summary", action="store_true", help="print warehouse stats only")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )

    if not args.summary:
        path = resolve(args.source)
        df = pd.read_parquet(path)
        result = load_observations(df, source=str(path.name))
        print(
            f"ETL run {result['run_id']}: {result['rows_in']:,} rows in, "
            f"{result['rows_upserted']:,} upserted, {result['cities']} cities, "
            f"{result['min_ts']} -> {result['max_ts']} in {result['seconds']}s"
        )
    for k, v in summary().items():
        print(f"  {k:<13} {v}")


if __name__ == "__main__":
    main()
