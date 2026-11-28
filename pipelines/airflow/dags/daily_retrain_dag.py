"""Daily ETL + retraining on newly fetched data — owned by MUDASSAR.

Every day at 02:00 UTC:

    fetch_new_data        Open-Meteo archive, only the days since the
                          latest row in the warehouse (incremental)
      -> validate         schema + quality gate; non-retryable on failure
      -> load_warehouse   idempotent UPSERT into Postgres `observations`
      -> build_features   from the WAREHOUSE, not from loose files
      -> train_candidate  residual LightGBM + XGBoost blend, logged to MLflow
      -> compare          candidate vs champion, re-scored on the SAME test split
      -> promote | keep   promote only if the gate passed AND it beats the
                          champion by min_improvement_over_production_pct

Nothing is promoted blindly: a candidate that fails the gate or does not
beat the deployed model is logged and discarded, and the champion keeps
serving. Every replaced champion is archived for rollback
(`python -m src.models.champion rollback`).

Trigger manually with options:
    airflow dags trigger daily_retrain_dag --conf '{"sample_frac": 0.3}'
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Not derived from __file__: inside the Airflow container the DAGs are
# mounted at /opt/airflow/dags while the project is at
# /opt/airflow/project, so parents[3] of this file would be "/".
# src.config knows where the project really is in both environments.
from src.config import PROJECT_ROOT

DEFAULT_ARGS = {
    "owner": "mudassar",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(hours=3),
    "email_on_failure": False,
}

FEATURES_PATH = PROJECT_ROOT / "data" / "processed" / "features_daily.parquet"


def fetch_new_data(**context):
    """Incremental extract: only the days the warehouse does not have yet."""
    import pandas as pd

    from src.data import ingestion
    from src.data.load_db import get_engine, latest_timestamp

    engine = get_engine()
    latest = latest_timestamp(engine)
    end = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).date()
    # Re-fetch the last stored day: the archive revises recent hours.
    start = latest.date() if latest is not None else None

    with engine.connect() as conn:
        n_cities = (
            conn.exec_driver_sql("SELECT count(*) FROM cities").scalar()
            if latest is not None
            else None
        )

    print(f"Warehouse latest={latest}; fetching {start or 'full history'} -> {end}")
    report = ingestion.backfill(
        limit=n_cities or None,
        start_date=start.isoformat() if start else None,
        end_date=end.isoformat(),
    )
    df = ingestion.combine_chunks()
    if start is not None:
        df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]
    if df.empty:
        raise AirflowSkipException("No new observations available upstream")

    path = PROJECT_ROOT / "data" / "interim" / f"daily_{context['ds_nodash']}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)

    context["ti"].xcom_push(key="path", value=str(path))
    print(
        f"Fetched {len(df):,} rows, {df.city_id.nunique()} cities; "
        f"failed chunks: {report['city_chunks_failed']}"
    )
    return len(df)


def validate(**context):
    import pandas as pd

    from src.data.validation import validate_raw

    path = context["ti"].xcom_pull(task_ids="fetch_new_data", key="path")
    ok, report = validate_raw(pd.read_parquet(path))
    failed = [c["check"] for c in report["quality"]["checks"] if not c["passed"]]
    print(f"Validation: {report['overall_status']}; failed: {failed}")
    if not ok:
        raise AirflowFailException(f"Data validation failed: {failed}")
    return report["overall_status"]


def load_warehouse(**context):
    import pandas as pd

    from src.data.load_db import load_observations, summary

    path = context["ti"].xcom_pull(task_ids="fetch_new_data", key="path")
    result = load_observations(pd.read_parquet(path), source=Path(path).name)
    print(f"ETL run {result['run_id']}: upserted {result['rows_upserted']:,} rows")
    print(f"Warehouse now: {summary()}")
    return result["rows_upserted"]


def build_features(**context):
    from src.data.load_db import extract_observations
    from src.features.preprocessing import build_features as build

    raw = extract_observations()
    features = build(raw)
    FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(FEATURES_PATH, index=False)
    print(
        f"Features: {len(features):,} rows x {features.shape[1]} cols -> {FEATURES_PATH}"
    )
    return len(features)


def train_candidate(**context):
    from src.models.train_base import run_training
    from src.models.train_lightgbm import LGB_DEFAULTS, build_blend

    conf = context["dag_run"].conf or {}
    sample_frac = conf.get("sample_frac")
    run_name = f"mudassar-blend-daily-{context['ds_nodash']}"

    metrics = run_training(
        model_family="blend",
        build_model=build_blend,
        params=dict(LGB_DEFAULTS),
        run_name=run_name,
        data_path=FEATURES_PATH,
        supports_eval_set=True,
        register=False,  # promotion is decided by the compare task, not here
        sample_frac=float(sample_frac) if sample_frac else None,
        metrics_filename="train_metrics_daily.json",
    )
    candidate = PROJECT_ROOT / "models" / "candidates" / run_name
    context["ti"].xcom_push(key="candidate", value=str(candidate))
    print(f"Candidate {run_name}: test MAE {metrics['test_mae']:.3f}")
    return metrics["test_mae"]


def compare(**context):
    import pandas as pd

    from src.features.splits import chrono_split
    from src.models.champion import compare as compare_models

    candidate = context["ti"].xcom_pull(task_ids="train_candidate", key="candidate")
    _, _, test = chrono_split(pd.read_parquet(FEATURES_PATH))
    decision = compare_models(Path(candidate), test)
    context["ti"].xcom_push(key="decision", value=decision)
    print(decision)
    return "promote_candidate" if decision["promote"] else "keep_champion"


def promote_candidate(**context):
    from src.models.champion import promote

    candidate = context["ti"].xcom_pull(task_ids="train_candidate", key="candidate")
    decision = context["ti"].xcom_pull(task_ids="compare_with_champion", key="decision")
    promote(Path(candidate), decision)
    print(f"PROMOTED: {decision['reason']}")


def keep_champion(**context):
    decision = context["ti"].xcom_pull(task_ids="compare_with_champion", key="decision")
    print(f"KEPT CHAMPION: {decision['reason']}")


with DAG(
    dag_id="daily_retrain_dag",
    description="Daily incremental ETL into Postgres, retrain, gated promotion",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 11, 1),
    schedule="0 2 * * *",  # daily, 02:00 UTC (07:00 PKT)
    catchup=False,
    max_active_runs=1,
    tags=["etl", "retraining", "daily", "airwatch"],
) as dag:
    t_fetch = PythonOperator(task_id="fetch_new_data", python_callable=fetch_new_data)
    t_validate = PythonOperator(task_id="validate", python_callable=validate, retries=0)
    t_load = PythonOperator(task_id="load_warehouse", python_callable=load_warehouse)
    t_features = PythonOperator(
        task_id="build_features", python_callable=build_features
    )
    t_train = PythonOperator(task_id="train_candidate", python_callable=train_candidate)
    t_compare = BranchPythonOperator(
        task_id="compare_with_champion", python_callable=compare, retries=0
    )
    t_promote = PythonOperator(
        task_id="promote_candidate", python_callable=promote_candidate
    )
    t_keep = PythonOperator(task_id="keep_champion", python_callable=keep_champion)
    t_end = EmptyOperator(task_id="end", trigger_rule="none_failed_min_one_success")

    t_fetch >> t_validate >> t_load >> t_features >> t_train >> t_compare
    t_compare >> [t_promote, t_keep] >> t_end
