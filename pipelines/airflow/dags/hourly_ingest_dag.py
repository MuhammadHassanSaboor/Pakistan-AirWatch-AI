"""Hourly ingestion and validation DAG.

Runs every hour: fetch the newest observations, validate them, load
them, and refresh the serving cache. A validation failure stops the
DAG rather than letting bad data reach the model — the task raises
AirflowFailException, which is non-retryable, because retrying a
schema violation would just fail eight more times.

Schedule: hourly, matching the upstream update cadence. Requesting
more often would waste the free-tier quota for no new information.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.operators.python import PythonOperator

# Airflow runs DAGs from its own working directory, so the project
# root has to be put on the path explicitly.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_ARGS = {
    "owner": "airwatch-team",
    "depends_on_past": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "execution_timeout": timedelta(minutes=25),
    "email_on_failure": False,
    "email_on_retry": False,
}


def fetch_live(**context):
    """Pull the latest hours for every city from Open-Meteo."""

    from src.data.cities import load_cities
    from src.serving.live_features import LiveFeatureStore

    store = LiveFeatureStore()
    store.refresh(force=True)
    observations = store._observations

    if observations is None or observations.empty:
        raise AirflowFailException("Open-Meteo returned no data for any city")

    path = f"/tmp/airwatch_live_{context['ts_nodash']}.parquet"
    observations.to_parquet(path, index=False)

    context["ti"].xcom_push(key="path", value=path)
    context["ti"].xcom_push(key="rows", value=int(len(observations)))
    context["ti"].xcom_push(key="cities", value=int(observations["city_id"].nunique()))

    expected = len(load_cities())
    got = observations["city_id"].nunique()
    if got < expected * 0.8:
        raise AirflowFailException(
            f"Only {got}/{expected} cities returned data — upstream degraded"
        )

    print(f"Fetched {len(observations):,} rows for {got} cities -> {path}")
    return int(len(observations))


def validate(**context):
    """Schema and quality gate. A failure here stops the pipeline."""
    import pandas as pd

    from src.data.validation import validate_raw

    path = context["ti"].xcom_pull(task_ids="fetch_live_data", key="path")
    df = pd.read_parquet(path)

    ok, report = validate_raw(df)
    context["ti"].xcom_push(key="report", value=report)

    failed = [c["check"] for c in report["quality"]["checks"] if not c["passed"]]
    print(f"Validation: {report['overall_status']}")
    if failed:
        print(f"Failed checks: {failed}")

    if not ok:
        # Non-retryable: a schema violation will not fix itself.
        raise AirflowFailException(
            f"Data validation failed: {failed or report['schema']['status']}"
        )
    return report["overall_status"]


def load_to_store(**context):
    """Persist validated observations for the API and for drift checks."""
    import pandas as pd

    path = context["ti"].xcom_pull(task_ids="fetch_live_data", key="path")
    df = pd.read_parquet(path)

    target = PROJECT_ROOT / "data" / "interim" / "live_latest.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(target, index=False)

    print(f"Wrote {len(df):,} rows -> {target}")
    return str(target)


def append_history(**context):
    """Append to the rolling window used for drift detection.

    Keeps 30 days. Evidently compares this against the training
    distribution; without a rolling store there is nothing to compare.
    """
    import pandas as pd

    path = context["ti"].xcom_pull(task_ids="fetch_live_data", key="path")
    new = pd.read_parquet(path)

    store = PROJECT_ROOT / "data" / "interim" / "live_history.parquet"
    store.parent.mkdir(parents=True, exist_ok=True)

    if store.exists():
        existing = pd.read_parquet(store)
        combined = pd.concat([existing, new], ignore_index=True)
    else:
        combined = new

    combined = combined.drop_duplicates(subset=["city_id", "timestamp"], keep="last")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
    combined = combined[combined["timestamp"] >= cutoff]
    combined.to_parquet(store, index=False)

    print(f"Rolling history: {len(combined):,} rows over 30 days")
    return int(len(combined))


def check_drift(**context):
    """Run Evidently against the training reference window."""
    from src.monitoring.drift import run_drift_check

    try:
        result = run_drift_check()
    except FileNotFoundError as exc:
        raise AirflowSkipException(f"Drift check skipped: {exc}") from exc

    context["ti"].xcom_push(key="psi_drift_share", value=result["psi_drift_share"])
    print(
        f"PSI drift: {result['psi_drift_share']:.2%} "
        f"({len(result['drifted_features'])}/{result['n_features']} features), "
        f"retrain_recommended={result['retrain_recommended']}"
    )
    return result["psi_drift_share"]


with DAG(
    dag_id="hourly_ingest_dag",
    description="Fetch, validate and load hourly air-quality observations",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 11, 1),
    schedule="0 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["ingestion", "production", "airwatch"],
) as dag:
    t_fetch = PythonOperator(
        task_id="fetch_live_data",
        python_callable=fetch_live,
    )

    t_validate = PythonOperator(
        task_id="validate_schema_and_quality",
        python_callable=validate,
        retries=0,  # schema failures are not transient
    )

    t_load = PythonOperator(
        task_id="load_to_store",
        python_callable=load_to_store,
    )

    t_history = PythonOperator(
        task_id="append_rolling_history",
        python_callable=append_history,
    )

    t_drift = PythonOperator(
        task_id="check_data_drift",
        python_callable=check_drift,
    )

    t_fetch >> t_validate >> t_load >> t_history >> t_drift
