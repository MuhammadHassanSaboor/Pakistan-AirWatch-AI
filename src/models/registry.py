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

import joblib
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
    # Every registry call takes the version as a string: the REST store
    # serialises it into a protobuf string field. See the note in
    # promote_to_production().
    c.transition_model_version_stage(MODEL_NAME, str(version), stage)
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
        MODEL_NAME, str(version), PRODUCTION, archive_existing_versions=True
    )
    # str(version), not version. MLflow's REST store puts this straight
    # into a protobuf whose `version` field is a string, and an int
    # raises "TypeError: bad argument type for built-in operation" from
    # inside protobuf -- after the stage transition has already
    # succeeded. The model went to Production with no record of who
    # approved it, which is the one thing these two tags exist to
    # prevent. Our tests did not catch it because they stub the MLflow
    # client, and a stub does not enforce protobuf field types.
    c.set_model_version_tag(MODEL_NAME, str(version), "approved_by", approved_by)
    c.set_model_version_tag(
        MODEL_NAME, str(version), "promoted_at", pd.Timestamp.now(tz="UTC").isoformat()
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
def _candidate_meta_for(run_id: str) -> tuple[Path, dict[str, Any]] | None:
    """Find the candidate directory produced by `run_id`.

    Matched on run_id and never on directory name: run names repeat
    (they are built from hyperparameters), so matching on the name
    would eventually pair a version with another run's weights.
    """
    candidates = PROJECT_ROOT / "models" / "candidates"
    if not candidates.is_dir():
        return None
    for meta_file in sorted(candidates.glob("*/metadata.json")):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("run_id") == run_id:
            return meta_file, meta
    return None


def _feature_names_for(run_id: str) -> list[str]:
    """The feature list, in training order, for the exported version.

    Not cosmetic. `ModelLoader.predict` uses this list to check for
    missing columns and to reorder the frame before calling the model.
    When it is empty that check is skipped entirely -- and a
    gradient-boosted model consumes columns positionally, so a frame
    assembled in a different order would produce confident nonsense
    rather than an error. The exported metadata therefore has to carry
    it; dropping it silently removed the guard.
    """
    found = _candidate_meta_for(run_id)
    if found is not None:
        names = found[1].get("feature_names") or []
        if names:
            return [str(n) for n in names]
    try:
        art = mlflow.artifacts.load_dict(f"runs:/{run_id}/feature_names.json")
        return [str(n) for n in (art.get("feature_names") or [])]
    except Exception:
        log.warning(
            "No feature_names found for run %s; ModelLoader will not be able "
            "to verify column order.",
            run_id[:8],
        )
        return []


#: MLflow flavour -> module exposing load_model, in preference order.
_FLAVOURS = {
    "xgboost": "mlflow.xgboost",
    "lightgbm": "mlflow.lightgbm",
    "sklearn": "mlflow.sklearn",
}


def _pickle_from_registry(pickle: Path, family: str) -> bool:
    """Load the Production model and write it as a pickle.

    Tries the flavour matching `family` first, then the others, so this
    keeps working when Mudassar's LightGBM models reach production.
    Returns True if a pickle was written.
    """
    order = [family] if family in _FLAVOURS else []
    order += [f for f in _FLAVOURS if f not in order]
    for flavour in order:
        try:
            module = __import__(_FLAVOURS[flavour], fromlist=["load_model"])
            model = module.load_model(f"models:/{MODEL_NAME}/{PRODUCTION}")
        except Exception:
            continue
        joblib.dump(model, pickle)
        log.info("Rebuilt model.pkl from the %s flavour", flavour)
        return True
    return False


def _sync_pickle(dest: Path, run_id: str, run, *, from_export: bool) -> None:
    """Make sure `model.pkl` in `dest` belongs to the exported version.

    MLflow stores an XGBoost model as `model.xgb` next to an `MLmodel`
    file; it never writes `model.pkl`. But the offline serving path
    (`ModelLoader._load_from_disk`) loads `model.pkl` and nothing else.

    So an export used to copy the new weights in as `model.xgb`,
    overwrite `metadata.json` with the new version's provenance, and
    leave whatever `model.pkl` happened to be there from a previous
    export untouched. The API then reported the new version through
    `/model-info` while predicting with the old weights -- the one
    claim a model registry exists to make, quietly false.

    Preference order: a pickle the registry itself carried, then the
    candidate directory saved by the run that produced this version,
    then re-serialising the MLflow artefact. If none of those can be
    had, the stale pickle is deleted rather than left to be served,
    because failing to start is better than serving the wrong model.
    """
    pickle = dest / "model.pkl"

    # 1. The registry artefacts themselves carried a pickle, so the
    #    file now on disk is this version's by construction.
    if from_export and pickle.exists():
        return

    # 2. The candidate directory written by the training run itself.
    found = _candidate_meta_for(run_id)
    if found is not None:
        meta_file, _meta = found
        source = meta_file.parent / "model.pkl"
        if source.exists():
            shutil.copy2(source, pickle)
            log.info("Synced model.pkl from candidate %s", meta_file.parent.name)
            return

    # 3. Re-serialise the MLflow artefact.
    family = (run.data.tags.get("model_family") or "").lower()
    if _pickle_from_registry(pickle, family):
        return

    # 4. Nothing trustworthy is available.
    if pickle.exists():
        pickle.unlink()
        log.error(
            "Could not produce a model.pkl for version %s; removed the stale "
            "one rather than let the API serve weights that do not match "
            "metadata.json. Copy it from models/candidates/<run>/model.pkl.",
            run_id[:8],
        )


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
    exported_pickle = False
    for item in Path(tmp).iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
        exported_pickle = exported_pickle or item.name == "model.pkl"

    c = client()
    run = c.get_run(prod["run_id"])

    _sync_pickle(dest, prod["run_id"], run, from_export=exported_pickle)
    (dest / "metadata.json").write_text(
        json.dumps(
            {
                "model_name": MODEL_NAME,
                "version": prod["version"],
                "stage": PRODUCTION,
                "run_id": prod["run_id"],
                "run_name": run.data.tags.get("mlflow.runName"),
                "model_family": run.data.tags.get("model_family"),
                "member": run.data.tags.get("member"),
                "dataset_version": run.data.tags.get("dataset_version"),
                "metrics": dict(run.data.metrics),
                "tags": dict(run.data.tags),
                # Required by ModelLoader to validate and order columns.
                "feature_names": _feature_names_for(prod["run_id"]),
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
