"""Dual-orchestration DAG: Airflow schedules, Kubeflow executes.

This is the architecture the course specification asks for in §3.4.
The division of labour is deliberate and worth being able to explain:

    Airflow  owns the data plane and the clock. It decides WHETHER
             and WHEN to train, validates inputs, and reacts to
             failure. It is cheap to run continuously.

    Kubeflow owns the ML workflow graph. Each step runs in its own
             container with its own CPU/memory limits, so a heavy
             training step cannot starve the scheduler, and steps can
             be retried or scaled independently.

Airflow triggers Kubeflow through the KFP client and polls for
completion. They never run duplicate workloads.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# In the Airflow container DAGs live at /opt/airflow/dags but the project
# is at /opt/airflow/project, so parents[3] of this file would be "/".
from src.config import PROJECT_ROOT

KFP_HOST = "http://host.docker.internal:8080"
PIPELINE_YAML = PROJECT_ROOT / "pipelines" / "kubeflow" / "compiled_pipeline.yaml"

DEFAULT_ARGS = {
    "owner": "airwatch-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(hours=3),
    "email_on_failure": False,
}


def revalidate_dataset(**context):
    """Full validation of the training dataset before any training.

    Training on silently-corrupted data is worse than not training:
    the resulting model passes every downstream check and is wrong.
    """
    import pandas as pd

    from src.config import DATA_CFG, resolve
    from src.data.validation import validate_raw

    path = resolve(DATA_CFG["paths"]["raw_combined"])
    if not path.exists():
        raise AirflowFailException(f"Training dataset not found: {path}")

    df = pd.read_parquet(path)
    ok, report = validate_raw(df)

    context["ti"].xcom_push(key="rows", value=int(len(df)))
    context["ti"].xcom_push(key="cities", value=int(df["city_id"].nunique()))

    if not ok:
        failed = [c["check"] for c in report["quality"]["checks"] if not c["passed"]]
        raise AirflowFailException(f"Dataset failed validation: {failed}")

    print(f"Validated {len(df):,} rows across {df['city_id'].nunique()} cities")
    return report["overall_status"]


def rebuild_features(**context):
    """Regenerate the feature table from the validated raw data."""
    import pandas as pd

    from src.config import DATA_CFG, resolve
    from src.data.cities import load_cities
    from src.features.preprocessing import build_features, feature_columns

    raw = pd.read_parquet(resolve(DATA_CFG["paths"]["raw_combined"]))
    features = build_features(raw, cities=load_cities())

    out = resolve(DATA_CFG["paths"]["processed"])
    out.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(out, index=False, compression="snappy")

    cols = feature_columns(features)
    context["ti"].xcom_push(key="n_features", value=len(cols))
    print(f"Built {len(features):,} rows x {len(cols)} features -> {out}")
    return int(len(features))


def trigger_kubeflow(**context):
    """Hand the ML graph over to Kubeflow Pipelines."""
    try:
        import kfp
    except ImportError as exc:
        raise AirflowSkipException(
            "kfp is not installed in the Airflow image; "
            "run the Kubeflow pipeline manually for the demonstration."
        ) from exc

    if not PIPELINE_YAML.exists():
        raise AirflowFailException(
            f"Compiled pipeline missing: {PIPELINE_YAML}. "
            "Run: python pipelines/kubeflow/pipeline_definition.py"
        )

    client = kfp.Client(host=KFP_HOST)
    run = client.create_run_from_pipeline_package(
        str(PIPELINE_YAML),
        arguments={
            "mae_threshold": 25.0,
            "max_depth": 8,
            "learning_rate": 0.05,
        },
        experiment_name="airwatch-training",
        run_name=f"airflow-triggered-{context['ts_nodash']}",
    )
    context["ti"].xcom_push(key="kfp_run_id", value=run.run_id)
    print(f"Kubeflow run started: {run.run_id}")
    return run.run_id


def wait_for_kubeflow(**context):
    """Poll Kubeflow until the pipeline finishes."""
    import kfp

    run_id = context["ti"].xcom_pull(
        task_ids="trigger_kubeflow_pipeline", key="kfp_run_id"
    )
    if not run_id:
        raise AirflowSkipException("No Kubeflow run to wait for")

    client = kfp.Client(host=KFP_HOST)
    deadline = time.time() + 2 * 60 * 60

    while time.time() < deadline:
        state = client.get_run(run_id).state
        print(f"Kubeflow run {run_id}: {state}")
        if state in ("SUCCEEDED", "FAILED", "ERROR", "SKIPPED"):
            if state != "SUCCEEDED":
                raise AirflowFailException(f"Kubeflow run ended as {state}")
            return state
        time.sleep(30)

    raise AirflowFailException("Timed out waiting for the Kubeflow pipeline")


def train_locally(**context):
    """Fallback path when Kubeflow is unavailable.

    The specification permits running infrastructure locally where
    cost makes a managed cluster impractical. This keeps the DAG
    useful on a laptop while the Kubeflow path remains the documented
    production route.
    """
    from src.models.train_base import run_training
    from src.models.train_xgboost import DEFAULTS, build_xgboost

    metrics = run_training(
        model_family="xgboost",
        build_model=build_xgboost,
        params=DEFAULTS,
        run_name=f"airflow-local-{context['ts_nodash']}",
        supports_eval_set=True,
    )
    context["ti"].xcom_push(key="test_mae", value=metrics["test_mae"])
    context["ti"].xcom_push(key="improvement_pct", value=metrics["improvement_pct"])
    return metrics["test_mae"]


with DAG(
    dag_id="ml_orchestrator_dag",
    description="Airflow validates and schedules; Kubeflow runs the ML graph",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 11, 1),
    schedule=None,  # triggered manually or by retraining_dag
    catchup=False,
    max_active_runs=1,
    tags=["training", "kubeflow", "airwatch"],
) as dag:
    start = EmptyOperator(task_id="start")

    t_validate = PythonOperator(
        task_id="revalidate_dataset",
        python_callable=revalidate_dataset,
        retries=0,
    )

    t_features = PythonOperator(
        task_id="rebuild_features",
        python_callable=rebuild_features,
    )

    t_trigger = PythonOperator(
        task_id="trigger_kubeflow_pipeline",
        python_callable=trigger_kubeflow,
    )

    t_wait = PythonOperator(
        task_id="wait_for_kubeflow",
        python_callable=wait_for_kubeflow,
    )

    t_local = PythonOperator(
        task_id="train_locally_fallback",
        python_callable=train_locally,
        trigger_rule="all_failed",  # only if the Kubeflow path failed
    )

    end = EmptyOperator(task_id="end", trigger_rule="none_failed_min_one_success")

    start >> t_validate >> t_features >> t_trigger >> t_wait
    t_wait >> end
    t_trigger >> t_local >> end
