"""Automated retraining with controlled promotion.

Implements the governance requirement that an automated pipeline must
NOT blindly promote every newly trained model. The decision chain is:

    drift or staleness detected?        -> branch, else skip
    candidate passes the quality gate?  -> else the DAG fails, nothing ships
    candidate beats the DEPLOYED model? -> else nothing ships
    human approval                      -> the final gate
    promote, redeploy, smoke test       -> auto-rollback on failure

Each of those is a separate task so the Airflow graph shows exactly
where a candidate was stopped.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_ARGS = {
    "owner": "airwatch-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(hours=4),
    "email_on_failure": False,
}

MAX_MODEL_AGE_DAYS = 30


def check_drift(**context):
    from src.monitoring.drift import run_drift_check

    try:
        result = run_drift_check()
    except FileNotFoundError as exc:
        print(f"No live history yet ({exc}); treating drift as zero")
        context["ti"].xcom_push(key="drift_share", value=0.0)
        return 0.0

    context["ti"].xcom_push(key="drift_share", value=result["drift_share"])
    print(f"Drift share: {result['drift_share']:.1%}")
    return result["drift_share"]


def check_model_age(**context):
    """How long has the deployed model been in production?"""
    from src.models.registry import production_version

    try:
        prod = production_version()
    except Exception as exc:
        print(f"Registry unavailable ({exc}); treating the model as stale")
        context["ti"].xcom_push(key="days_old", value=999)
        return 999

    if not prod:
        print("No production model yet — retraining is required")
        context["ti"].xcom_push(key="days_old", value=999)
        return 999

    created = datetime.fromisoformat(prod["created"].replace("Z", "+00:00"))
    days = (datetime.now(created.tzinfo) - created).days
    context["ti"].xcom_push(key="days_old", value=days)
    print(f"Production model v{prod['version']} is {days} days old")
    return days


def decide(**context):
    """Branch: retrain only when there is a reason to."""
    ti = context["ti"]
    drift = ti.xcom_pull(task_ids="check_drift", key="drift_share") or 0.0
    age = ti.xcom_pull(task_ids="check_model_age", key="days_old") or 0
    manual = context["dag_run"].conf.get("force_retrain", False)

    reasons = []
    if drift > 0.30:
        reasons.append(f"data drift {drift:.1%} exceeds 30%")
    if age > MAX_MODEL_AGE_DAYS:
        reasons.append(f"model is {age} days old")
    if manual:
        reasons.append("manually forced")

    if reasons:
        print("Retraining because: " + "; ".join(reasons))
        ti.xcom_push(key="reasons", value=reasons)
        return "retrain_candidate"

    print("No drift and the model is fresh — skipping retraining")
    return "skip_retraining"


def retrain(**context):
    """Train a candidate on the current data."""
    from src.models.train_base import run_training
    from src.models.train_xgboost import DEFAULTS, build_xgboost

    metrics = run_training(
        model_family="xgboost",
        build_model=build_xgboost,
        params=DEFAULTS,
        run_name=f"retrain-{context['ts_nodash']}",
        supports_eval_set=True,
    )
    ti = context["ti"]
    ti.xcom_push(key="test_mae", value=float(metrics["test_mae"]))
    ti.xcom_push(key="improvement_pct", value=float(metrics["improvement_pct"]))
    return metrics["test_mae"]


def compare_with_production(**context):
    """The gate the specification cares about most.

    A candidate must be meaningfully BETTER than what is already
    deployed. Without this, every scheduled retrain would churn
    production for noise-level differences.
    """
    from src.config import quality_gate
    from src.models.evaluate import check_quality_gate
    from src.models.registry import production_metrics

    ti = context["ti"]
    candidate_mae = ti.xcom_pull(task_ids="retrain_candidate", key="test_mae")
    improvement = ti.xcom_pull(task_ids="retrain_candidate", key="improvement_pct")

    if candidate_mae is None:
        raise AirflowFailException("Candidate produced no test_mae")

    current = production_metrics()
    prod_mae = current.get("test_mae")

    metrics = {"test_mae": candidate_mae, "improvement_pct": improvement}
    passed, reasons = check_quality_gate(metrics, production_mae=prod_mae)

    print(f"Candidate MAE : {candidate_mae:.3f}")
    print(f"Production MAE: {prod_mae if prod_mae else 'none deployed'}")
    print(f"Gate threshold: {quality_gate()}")

    if not passed:
        # Failing here turns the DAG red and stops the deployment
        # chain. That red task IS the demonstration that a bad model
        # cannot reach production.
        raise AirflowFailException(
            "Quality gate REJECTED the candidate:\n"
            + "\n".join(f"  - {r}" for r in reasons)
        )

    print("Candidate passed every gate — eligible for Staging")
    return candidate_mae


def promote_staging(**context):
    from src.models.registry import best_run, promote

    best = best_run()
    if not best:
        raise AirflowSkipException("No runs found in the registry")

    version = promote(best["run_id"], "Staging")
    context["ti"].xcom_push(key="version", value=version)
    print(f"Promoted version {version} to Staging")
    return version


def await_approval(**context):
    """The human gate.

    Deliberately a task that must be cleared by a person in the
    Airflow UI. Automating this away would defeat the point: the
    specification requires that deployment is not fully automatic.
    """
    approved = context["dag_run"].conf.get("approved", False)
    if not approved:
        raise AirflowSkipException(
            "Waiting for human approval. Re-run this DAG with "
            '{"approved": true} once the team has reviewed the '
            "candidate's metrics and error breakdown in MLflow."
        )
    print("Approval recorded — proceeding to production")
    return True


def promote_production(**context):
    from src.models.registry import promote_to_production

    version = context["ti"].xcom_pull(task_ids="promote_to_staging", key="version")
    promoted = promote_to_production(version, approved_by="airflow-retraining")
    print(f"Version {promoted} is now in Production")
    return promoted


def smoke_test(**context):
    """Verify the deployed service actually serves the new model."""
    import requests

    url = context["dag_run"].conf.get("api_url", "http://host.docker.internal:5000")
    expected = str(context["ti"].xcom_pull(task_ids="promote_to_production"))

    try:
        health = requests.get(f"{url}/health", timeout=10)
        info = requests.get(f"{url}/model-info", timeout=10).json()
    except Exception as exc:
        raise AirflowFailException(f"API unreachable after promotion: {exc}") from exc

    if health.status_code != 200:
        raise AirflowFailException(f"/health returned {health.status_code}")

    served = str(info.get("model_version"))
    print(f"API is serving version {served}; expected {expected}")
    if served != expected:
        raise AirflowFailException(
            f"API still serving v{served}, not the promoted v{expected}. "
            "Restart the service or check MODEL_SOURCE."
        )
    return served


def rollback(**context):
    """Automatic rollback when the smoke test fails."""
    from src.models.registry import rollback as do_rollback

    version = do_rollback()
    print(f"ROLLED BACK to version {version}")
    return version


with DAG(
    dag_id="retraining_dag",
    description="Drift-triggered retraining with controlled promotion",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 11, 1),
    schedule="0 3 * * 0",  # weekly, Sunday 03:00 UTC
    catchup=False,
    max_active_runs=1,
    tags=["retraining", "governance", "airwatch"],
) as dag:
    t_drift = PythonOperator(task_id="check_drift", python_callable=check_drift)
    t_age = PythonOperator(task_id="check_model_age", python_callable=check_model_age)

    t_decide = BranchPythonOperator(task_id="decide_retraining", python_callable=decide)

    t_skip = EmptyOperator(task_id="skip_retraining")

    t_retrain = PythonOperator(task_id="retrain_candidate", python_callable=retrain)

    t_compare = PythonOperator(
        task_id="compare_with_production",
        python_callable=compare_with_production,
        retries=0,  # a rejected candidate must not be retried
    )

    t_staging = PythonOperator(
        task_id="promote_to_staging", python_callable=promote_staging
    )

    t_approval = PythonOperator(
        task_id="await_human_approval", python_callable=await_approval, retries=0
    )

    t_production = PythonOperator(
        task_id="promote_to_production", python_callable=promote_production
    )

    t_smoke = PythonOperator(
        task_id="smoke_test_deployment", python_callable=smoke_test, retries=1
    )

    t_rollback = PythonOperator(
        task_id="rollback_on_failure",
        python_callable=rollback,
        trigger_rule="one_failed",
    )

    t_end = EmptyOperator(task_id="end", trigger_rule="none_failed_min_one_success")

    [t_drift, t_age] >> t_decide
    t_decide >> t_skip >> t_end
    (
        t_decide
        >> t_retrain
        >> t_compare
        >> t_staging
        >> t_approval
        >> t_production
        >> t_smoke
        >> t_end
    )
    t_smoke >> t_rollback
