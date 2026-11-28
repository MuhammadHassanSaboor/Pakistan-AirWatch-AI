"""Copy locally-logged MLflow runs onto the shared DagsHub server.

Why this exists
---------------
`src/models/tracking.py` falls back to a local `mlruns/` directory when
no MLflow credentials are present, so the project stays runnable for
anyone who clones the public repo. That fallback worked: the first
seven runs of this project were logged to disk on one laptop, where
nobody else could see them.

The team comparison is the whole point of logging runs in the first
place -- three members, three model families, one table -- so those
runs have to live on the shared server. This script moves them there
without retraining, because the metrics are already real: retraining
XGBoost takes 28 minutes and would produce the same numbers.

What is preserved
-----------------
Run name, status, start and end timestamps, every param, the full
history of every metric (timestamps and steps included), every tag,
and all artifacts. The copy is therefore indistinguishable from the
original except for its run id, which MLflow always assigns itself.

Two tags are *added* so the provenance is never ambiguous:

    migrated_from   the source run id on the local store
    migrated_at     when the copy was made

Nothing is relabelled. In particular `member` is copied exactly as it
was recorded, including `unknown` -- inventing attribution for a run
would corrupt the one table this project is graded on.

Which runs are comparable
-------------------------
These six runs predate DVC tracking, so none of them recorded a
dataset hash -- they are all tagged `dataset_version: untracked`, and
no amount of post-hoc inspection can recover what they trained on.
That matters, because comparing a model trained on one feature table
against a model trained on another is exactly the mistake this
project is supposed to demonstrate avoiding.

File mtimes cannot answer it: `dvc commit` rewrites a workspace file
when it links it into the cache, so `features.parquet` now carries
today's timestamp regardless of when it was built.

What does answer it is the data itself. Every training script also
evaluates a persistence baseline on its own test split and logs the
result as `baseline_mae`. Two runs that saw the same split compute the
same number, to the full float. So `dataset_cohort` is tagged with
that value: **runs sharing a cohort are mutually comparable, and runs
in different cohorts are not**, whatever their metrics look like
side by side.

Runs logged from now on carry a real `dataset_version` md5 taken from
`dvc.lock`, which is strictly better -- see `tracking.dataset_version`.
`dataset_cohort` exists to salvage the runs logged before that worked.

Usage
-----
    python scripts/migrate_mlflow_runs.py --dry-run
    python scripts/migrate_mlflow_runs.py
    python scripts/migrate_mlflow_runs.py --include-failed
    python scripts/migrate_mlflow_runs.py --skip-artifacts

Re-running is safe: a source run already present on the remote is
skipped, matched by its `migrated_from` tag.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from mlflow.entities import Metric, Param, RunStatus, RunTag
from mlflow.tracking import MlflowClient

# Run as `python scripts/migrate_mlflow_runs.py` from anywhere in the
# repo without needing PYTHONPATH set or the package installed, because
# "it says No module named src" is where a teammate gives up.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import PROJECT_ROOT, settings

log = logging.getLogger("migrate")

# MLflow refuses to accept its own reserved tags on a new run; they are
# set by the server or derived from the run itself.
RESERVED_TAG_PREFIXES = ("mlflow.",)

# log_batch caps each call at 1000 metrics / 100 params / 100 tags.
BATCH = 90


def dataset_cohort(run) -> str | None:
    """A fingerprint of the data a run was evaluated on.

    `baseline_mae` is the error of a persistence forecast on the run's
    own test split. It depends only on the data, not on the model, so
    two runs that saw the same split agree on it exactly and two runs
    that did not, do not. Full repr, no rounding: rounding would merge
    cohorts that differ in the fourth decimal.
    """
    value = run.data.metrics.get("baseline_mae")
    return repr(float(value)) if value is not None else None


def local_client() -> MlflowClient:
    """A client bound to the on-disk store, regardless of env vars."""
    uri = (PROJECT_ROOT / "mlruns").as_uri()
    return MlflowClient(tracking_uri=uri)


def remote_client() -> MlflowClient:
    """A client bound to the DagsHub tracking server."""
    if not settings.mlflow_configured:
        raise SystemExit(
            "MLflow credentials are not configured. Set MLFLOW_TRACKING_URI, "
            "MLFLOW_TRACKING_USERNAME and MLFLOW_TRACKING_PASSWORD in .env"
        )
    os.environ["MLFLOW_TRACKING_USERNAME"] = settings.mlflow_username
    os.environ["MLFLOW_TRACKING_PASSWORD"] = settings.mlflow_password
    return MlflowClient(tracking_uri=settings.mlflow_tracking_uri)


def ensure_experiment(client: MlflowClient, name: str) -> str:
    exp = client.get_experiment_by_name(name)
    if exp is not None:
        return exp.experiment_id
    log.info("Creating experiment %r on the remote", name)
    return client.create_experiment(name)


def already_migrated(client: MlflowClient, experiment_id: str) -> dict[str, str]:
    """Map source run id -> remote run id for runs copied previously."""
    done: dict[str, str] = {}
    for run in client.search_runs([experiment_id], max_results=1000):
        src = run.data.tags.get("migrated_from")
        if src:
            done[src] = run.info.run_id
    return done


def _chunks(seq: list, size: int = BATCH):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def copy_run(
    src: MlflowClient,
    dst: MlflowClient,
    run,
    experiment_id: str,
    *,
    with_artifacts: bool = True,
) -> str:
    """Recreate one run on the destination server. Returns its run id."""
    info, data = run.info, run.data
    name = data.tags.get("mlflow.runName") or info.run_id[:8]

    tags = {
        k: v for k, v in data.tags.items() if not k.startswith(RESERVED_TAG_PREFIXES)
    }
    tags["migrated_from"] = info.run_id
    tags["migrated_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    cohort = dataset_cohort(run)
    if cohort is not None:
        tags["dataset_cohort"] = cohort
    # These runs were logged before DVC was initialised, so no dataset
    # hash exists for them. Say so explicitly rather than leaving the
    # absence to be interpreted.
    tags.setdefault("dataset_provenance", "pre-dvc-tracking")

    created = dst.create_run(
        experiment_id=experiment_id,
        start_time=info.start_time,
        tags={"mlflow.runName": name, **tags},
        run_name=name,
    )
    run_id = created.info.run_id

    params = [Param(k, str(v)) for k, v in data.params.items()]
    for batch in _chunks(params):
        dst.log_batch(run_id, params=batch)

    # Full history, not the latest value: a metric logged per-epoch has
    # a curve, and flattening it to one point throws the curve away.
    metrics: list[Metric] = []
    for key in data.metrics:
        for m in src.get_metric_history(info.run_id, key):
            metrics.append(Metric(m.key, m.value, m.timestamp, m.step))
    for batch in _chunks(metrics, 900):
        dst.log_batch(run_id, metrics=batch)

    extra = [RunTag(k, str(v)) for k, v in tags.items()]
    for batch in _chunks(extra):
        dst.log_batch(run_id, tags=batch)

    if with_artifacts:
        _copy_artifacts(src, dst, info.run_id, run_id)

    dst.set_terminated(
        run_id,
        status=RunStatus.to_string(RunStatus.from_string(info.status)),
        end_time=info.end_time,
    )
    return run_id


def _copy_artifacts(
    src: MlflowClient, dst: MlflowClient, src_run: str, dst_run: str
) -> None:
    try:
        listing = src.list_artifacts(src_run)
    except Exception:
        log.warning("  could not list artifacts for %s", src_run[:8])
        return
    if not listing:
        return

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for item in listing:
            try:
                src.download_artifacts(src_run, item.path, str(root))
            except Exception:
                log.warning("  download failed: %s", item.path)
        for child in sorted(root.iterdir()):
            try:
                if child.is_dir():
                    dst.log_artifacts(dst_run, str(child), artifact_path=child.name)
                else:
                    dst.log_artifact(dst_run, str(child))
            except Exception as exc:
                log.warning("  upload failed: %s (%s)", child.name, exc)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--experiment",
        default=settings.mlflow_experiment,
        help="experiment name on both ends (default: from .env)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be copied and exit",
    )
    ap.add_argument(
        "--include-failed",
        action="store_true",
        help="also copy runs whose status is FAILED (skipped by default)",
    )
    ap.add_argument(
        "--skip-artifacts",
        action="store_true",
        help="copy metrics/params/tags only; much faster",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    src = local_client()
    src_exp = src.get_experiment_by_name(args.experiment)
    if src_exp is None:
        raise SystemExit(f"No local experiment named {args.experiment!r} in mlruns/")

    runs = src.search_runs([src_exp.experiment_id], max_results=1000)
    runs = sorted(runs, key=lambda r: r.info.start_time)
    if not args.include_failed:
        kept = [r for r in runs if r.info.status != "FAILED"]
        if len(kept) != len(runs):
            log.info(
                "Skipping %d failed run(s); pass --include-failed to copy them",
                len(runs) - len(kept),
            )
        runs = kept

    log.info("Local experiment %r: %d run(s) to consider", args.experiment, len(runs))

    if args.dry_run:
        for r in runs:
            log.info(
                "  %s  %-28s member=%-9s family=%-9s test_mae=%s",
                r.info.run_id[:8],
                r.data.tags.get("mlflow.runName"),
                r.data.tags.get("member", "-"),
                r.data.tags.get("model_family", "-"),
                round(r.data.metrics.get("test_mae", float("nan")), 4),
            )
        log.info("Dry run: nothing was written.")
        return

    dst = remote_client()
    exp_id = ensure_experiment(dst, args.experiment)
    done = already_migrated(dst, exp_id)

    copied = 0
    for r in runs:
        name = r.data.tags.get("mlflow.runName")
        if r.info.run_id in done:
            log.info("= %-28s already on remote (%s)", name, done[r.info.run_id][:8])
            continue
        log.info("+ %-28s copying...", name)
        new_id = copy_run(
            src,
            dst,
            r,
            exp_id,
            with_artifacts=not args.skip_artifacts,
        )
        log.info("  -> %s", new_id)
        copied += 1

    log.info("\nDone. %d run(s) copied, %d already present.", copied, len(done))
    log.info(
        "View them at: %s/experiments",
        settings.mlflow_tracking_uri.replace(".mlflow", ""),
    )


if __name__ == "__main__":
    main()
