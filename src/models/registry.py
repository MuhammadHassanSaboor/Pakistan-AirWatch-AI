"""Model registry operations: promotion, rollback, comparison.

Implements the governance requirement that an automated pipeline must
never blindly promote every newly trained model. The flow is:

    run  ->  registered version  ->  Staging  ->  [quality gate]
                                             ->  [human approval]
                                             ->  Production

and `rollback()` reverses the last promotion in seconds.

CLI
---
    python -m src.models.registry list
    python -m src.models.registry best
    python -m src.models.registry compare
    python -m src.models.registry promote --run-id <id> --stage Staging
    python -m src.models.registry promote-production --version 7
    python -m src.models.registry rollback
    python -m src.models.registry export-production
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
from mlflow.tracking import MlflowClient

from src.config import MODEL_CFG, PROJECT_ROOT, settings
from src.models.evaluate import check_quality_gate
from src.models.tracking import configure

log = logging.getLogger(__name__)

MODEL_NAME = MODEL_CFG["registry"]["model_name"]
STAGING = MODEL_CFG["registry"]["staging_stage"]
PRODUCTION = MODEL_CFG["registry"]["production_stage"]


def client() -> MlflowClient:
    configure()
    return MlflowClient()


# ──────────────────────────────────────────────────────────────
# Querying
# ──────────────────────────────────────────────────────────────
def search_runs(experiment: str | None = None) -> pd.DataFrame:
    """All runs in the shared experiment, newest first."""
    configure()
    exp_name = experiment or settings.mlflow_experiment
    df = mlflow.search_runs(experiment_names=[exp_name])
    if df.empty:
        log.warning("No runs found in experiment '%s'", exp_name)
    return df


def comparison_table(experiment: str | None = None) -> pd.DataFrame:
    """The three-member comparison table used in the report."""
    runs = search_runs(experiment)
    if runs.empty:
        return pd.DataFrame()

    wanted = {
        "tags.member": "member",
        "tags.model_family": "model_family",
        "tags.quality_gate": "gate",
        "metrics.test_mae": "test_mae",
        "metrics.test_rmse": "test_rmse",
        "metrics.test_r2": "test_r2",
        "metrics.mae_h1": "mae_h1",
        "metrics.mae_h24": "mae_h24",
        "metrics.baseline_mae": "baseline_mae",
        "metrics.improvement_pct": "improvement_pct",
        "metrics.train_seconds": "train_seconds",
        "tags.mlflow.runName": "run_name",
        "run_id": "run_id",
    }
    present = {k: v for k, v in wanted.items() if k in runs.columns}
    tbl = runs[list(present)].rename(columns=present)
    if "test_mae" in tbl.columns:
        tbl = tbl.sort_values("test_mae", na_position="last")
    return tbl.reset_index(drop=True)


def best_run(experiment: str | None = None) -> dict[str, Any] | None:
    """Lowest test_mae, with mae_h24 as the tie-breaker."""
    tbl = comparison_table(experiment)
    if tbl.empty or "test_mae" not in tbl.columns:
        return None
    tbl = tbl.dropna(subset=["test_mae"])
    if tbl.empty:
        return None
    sort_cols = ["test_mae"] + (["mae_h24"] if "mae_h24" in tbl.columns else [])
    return tbl.sort_values(sort_cols).iloc[0].to_dict()


def list_versions() -> list[dict[str, Any]]:
    c = client()
    try:
        versions = c.search_model_versions(f"name='{MODEL_NAME}'")
    except Exception as exc:
        log.error("Could not read the registry: %s", exc)
        return []
    return [
        {
            "version": int(v.version),
            "stage": v.current_stage,
            "run_id": v.run_id,
            "status": v.status,
            "created": pd.to_datetime(v.creation_timestamp, unit="ms").isoformat(),
        }
        for v in sorted(versions, key=lambda v: int(v.version), reverse=True)
    ]


def production_version() -> dict[str, Any] | None:
    for v in list_versions():
        if v["stage"] == PRODUCTION:
            return v
    return None


def production_metrics() -> dict[str, float]:
    """Metrics of the currently deployed model, for candidate comparison."""
    prod = production_version()
    if not prod:
        return {}
    c = client()
    try:
        return dict(c.get_run(prod["run_id"]).data.metrics)
    except Exception as exc:
        log.warning("Could not read production metrics: %s", exc)
        return {}


# ──────────────────────────────────────────────────────────────
# Transitions
# ──────────────────────────────────────────────────────────────
def _version_for_run(run_id: str) -> int:
    for v in list_versions():
        if v["run_id"] == run_id:
            return v["version"]
    raise ValueError(
        f"No registered model version found for run {run_id}. "
        "Was the run logged with register=True and did it pass the gate?"
    )


def promote(run_id: str, stage: str = STAGING) -> int:
    """Move the version produced by `run_id` to `stage`."""
    version = _version_for_run(run_id)
    c = client()
    c.transition_model_version_stage(MODEL_NAME, version, stage)
    log.info("Model %s v%d -> %s", MODEL_NAME, version, stage)
    return version


def promote_to_production(version: int, approved_by: str = "team-review") -> int:
    """Promote to Production, but only through the quality gate.

    This function is deliberately the ONLY path to production. The
    Airflow DAG, the Kubeflow pipeline and the CLI all call it, so the
    gate cannot be bypassed by using a different entry point.
    """
    c = client()
    mv = c.get_model_version(MODEL_NAME, str(version))
    metrics = dict(c.get_run(mv.run_id).data.metrics)

    current = production_metrics()
    prod_mae = current.get("test_mae")

    passed, reasons = check_quality_gate(metrics, production_mae=prod_mae)
    if not passed:
        raise RuntimeError(
            "Quality gate REJECTED this candidate; it will not be deployed.\n"
            + "\n".join(f"  - {r}" for r in reasons)
        )

    c.transition_model_version_stage(
        MODEL_NAME, version, PRODUCTION, archive_existing_versions=True
    )
    c.set_model_version_tag(MODEL_NAME, version, "approved_by", approved_by)
    c.set_model_version_tag(
        MODEL_NAME, version, "promoted_at", pd.Timestamp.now(tz="UTC").isoformat()
    )
    log.info(
        "Model %s v%d -> %s (approved by %s)",
        MODEL_NAME,
        version,
        PRODUCTION,
        approved_by,
    )
    return version


def rollback() -> int:
    """Return the most recently archived version to Production."""
    archived = [v for v in list_versions() if v["stage"] == "Archived"]
    if not archived:
        raise RuntimeError("No archived version available to roll back to.")

    previous = max(archived, key=lambda v: v["version"])
    c = client()
    c.transition_model_version_stage(
        MODEL_NAME, previous["version"], PRODUCTION, archive_existing_versions=True
    )
    c.set_model_version_tag(
        MODEL_NAME,
        previous["version"],
        "rolled_back_at",
        pd.Timestamp.now(tz="UTC").isoformat(),
    )
    log.warning(
        "ROLLBACK: %s v%d restored to Production", MODEL_NAME, previous["version"]
    )
    return previous["version"]


# ──────────────────────────────────────────────────────────────
# Local export (so the API can run without network access)
# ──────────────────────────────────────────────────────────────
def export_production(dest: str | Path | None = None) -> Path:
    """Copy the Production model to models/production/ for offline serving."""
    dest = Path(dest or PROJECT_ROOT / "models" / "production")
    prod = production_version()
    if not prod:
        raise RuntimeError("No model is currently in Production.")

    configure()
    dest.mkdir(parents=True, exist_ok=True)
    uri = f"models:/{MODEL_NAME}/{PRODUCTION}"
    log.info("Downloading %s ...", uri)

    tmp = mlflow.artifacts.download_artifacts(artifact_uri=uri)
    for item in Path(tmp).iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)

    c = client()
    run = c.get_run(prod["run_id"])
    (dest / "metadata.json").write_text(
        json.dumps(
            {
                "model_name": MODEL_NAME,
                "version": prod["version"],
                "stage": PRODUCTION,
                "run_id": prod["run_id"],
                "metrics": dict(run.data.metrics),
                "tags": dict(run.data.tags),
                "exported_at": pd.Timestamp.now(tz="UTC").isoformat(),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    log.info("Exported Production v%d -> %s", prod["version"], dest)
    return dest


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="MLflow model registry operations")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list registered versions")
    sub.add_parser("best", help="show the best run")
    sub.add_parser("rollback", help="restore the previous production model")
    sub.add_parser("production", help="show the current production model")

    p_cmp = sub.add_parser("compare", help="print the member comparison table")
    p_cmp.add_argument("--output", default="Documents/MODEL_COMPARISON.md")
    p_cmp.add_argument("--csv", default="reports/all_runs.csv")

    p_pro = sub.add_parser("promote", help="move a run's version to a stage")
    p_pro.add_argument("--run-id", required=True)
    p_pro.add_argument("--stage", default=STAGING)

    p_prod = sub.add_parser("promote-production", help="promote through the gate")
    p_prod.add_argument("--version", type=int, required=True)
    p_prod.add_argument("--approved-by", default="team-review")

    p_exp = sub.add_parser("export-production", help="copy the model locally")
    p_exp.add_argument("--dest")

    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    if args.command == "list":
        versions = list_versions()
        if not versions:
            print("No registered versions.")
            return
        print(f"\n{MODEL_NAME}")
        print(f"{'ver':>4}  {'stage':<12} {'run_id':<34} created")
        for v in versions:
            print(
                f"{v['version']:>4}  {v['stage']:<12} {v['run_id']:<34} "
                f"{v['created'][:19]}"
            )

    elif args.command == "best":
        b = best_run()
        print(json.dumps(b, indent=2, default=str) if b else "No runs found.")

    elif args.command == "production":
        p = production_version()
        if not p:
            print("No model in Production.")
            return
        print(json.dumps({**p, "metrics": production_metrics()}, indent=2, default=str))

    elif args.command == "compare":
        tbl = comparison_table()
        if tbl.empty:
            print("No runs found.")
            return
        csv_path = PROJECT_ROOT / args.csv
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        tbl.to_csv(csv_path, index=False)

        best_per = (
            tbl.dropna(subset=["test_mae"])
            .sort_values("test_mae")
            .groupby(["member", "model_family"], as_index=False)
            .first()
            .sort_values("test_mae")
        )
        print("\nBest run per member and model family:\n")
        print(best_per.to_string(index=False))
        print(f"\nAll {len(tbl)} runs -> {csv_path}")

    elif args.command == "promote":
        v = promote(args.run_id, args.stage)
        print(f"Promoted run {args.run_id} -> {MODEL_NAME} v{v} ({args.stage})")

    elif args.command == "promote-production":
        v = promote_to_production(args.version, args.approved_by)
        print(f"{MODEL_NAME} v{v} is now in Production.")

    elif args.command == "rollback":
        v = rollback()
        print(f"Rolled back. {MODEL_NAME} v{v} is now in Production.")

    elif args.command == "export-production":
        dest = export_production(args.dest)
        print(f"Exported to {dest}")


if __name__ == "__main__":
    main()
