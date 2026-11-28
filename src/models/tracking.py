"""MLflow tracking helpers shared by all three team members.

Why this module exists
----------------------
Hassan, Mudassar and Ifraz each train different model families, but
their runs must land in ONE experiment with identical tag and metric
names, otherwise the comparison table cannot be built. This module is
the only place that talks to MLflow, so consistency is structural
rather than a matter of remembering.

It also degrades gracefully: with no DagsHub credentials in `.env`,
runs are logged to a local `mlruns/` folder instead of failing. That
keeps the project runnable for anyone who clones the public repo.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import mlflow

from src.config import MODEL_CFG, PROJECT_ROOT, settings

log = logging.getLogger(__name__)


def git_commit() -> str:
    """Short SHA of the current commit, for exact reproducibility."""
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=PROJECT_ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def git_dirty() -> bool:
    """True when uncommitted changes exist — the run is not reproducible."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode()
        return bool(out.strip())
    except Exception:
        return False


def dataset_version(path: str | Path) -> str:
    """MD5 recorded by DVC for a tracked dataset.

    Links each MLflow run to the exact bytes it trained on, which is
    what makes "reproduce run 42" a real operation, and what lets three
    people confirm they compared models on identical data rather than
    on three different downloads of a rolling API.

    Two layouts have to be read, because DVC records hashes in two
    different places:

      * ``dvc.lock`` -- for files produced by a *pipeline* stage, which
        is every dataset in this project. The hash lives under
        ``stages.<name>.outs[].md5``.
      * ``<path>.dvc`` -- the sidecar written by a bare ``dvc add``.

    Only the sidecar was checked before, so every pipeline output
    looked untracked and every run was tagged ``dataset_version:
    untracked`` -- the one tag that makes a comparison table
    trustworthy, silently absent.

    Separators are normalised by string replacement rather than by
    ``Path.as_posix()``, which is **platform dependent**: on Windows
    ``Path(r"data\\x.parquet").as_posix()`` yields ``data/x.parquet``,
    but on Linux a backslash is an ordinary filename character, so the
    same call returns it unchanged and the lookup silently misses.
    Doing it as a plain string makes the result identical everywhere.
    (This is not hypothetical: it passed locally on Windows and failed
    on the Linux CI runner.)
    """
    # Normalise first, so the separator style cannot depend on the OS.
    wanted = str(path).replace("\\", "/")

    root = PROJECT_ROOT.as_posix().replace("\\", "/").rstrip("/")
    if wanted.startswith(f"{root}/"):
        wanted = wanted[len(root) + 1 :]
    # A path from outside the repo stays absolute; it simply will not
    # match anything in dvc.lock, which is the correct answer.
    wanted = wanted.removeprefix("./")

    lock = PROJECT_ROOT / "dvc.lock"
    if lock.exists():
        try:
            import yaml

            doc = yaml.safe_load(lock.read_text(encoding="utf-8")) or {}
            for stage in (doc.get("stages") or {}).values():
                for out in stage.get("outs") or []:
                    if out.get("path") == wanted and out.get("md5"):
                        return str(out["md5"])
        except Exception:
            log.debug("Could not read dvc.lock for %s", wanted, exc_info=True)

    sidecar = PROJECT_ROOT / f"{wanted}.dvc"
    if sidecar.exists():
        try:
            import yaml

            doc = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
            for out in doc.get("outs") or []:
                if out.get("md5"):
                    return str(out["md5"])
        except Exception:
            log.debug("Could not read %s", sidecar, exc_info=True)

    return "untracked"


def configure() -> bool:
    """Point MLflow at DagsHub, or fall back to a local store.

    Returns True when the remote tracking server is in use.
    """
    if settings.mlflow_configured:
        # MLflow's HTTP client reads credentials from the environment.
        os.environ["MLFLOW_TRACKING_USERNAME"] = settings.mlflow_username
        os.environ["MLFLOW_TRACKING_PASSWORD"] = settings.mlflow_password
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment)
        log.info(
            "MLflow -> %s (experiment: %s)",
            settings.mlflow_tracking_uri,
            settings.mlflow_experiment,
        )
        return True

    local = PROJECT_ROOT / "mlruns"
    mlflow.set_tracking_uri(local.as_uri())
    mlflow.set_experiment(settings.mlflow_experiment)
    log.warning(
        "No MLflow credentials found — logging locally to %s. "
        "Set MLFLOW_TRACKING_* in .env to share runs with the team.",
        local,
    )
    return False


def standard_tags(
    model_family: str,
    data_path: str | Path | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The tag set every run must carry.

    `member` is what lets us produce a per-person comparison table.
    """
    tags = {
        "member": settings.member,
        "model_family": model_family,
        "git_commit": git_commit(),
        "git_dirty": str(git_dirty()).lower(),
        "target": MODEL_CFG["target"],
        "horizons": ",".join(str(h) for h in MODEL_CFG["horizons"]),
        "train_end": MODEL_CFG["split"]["train_end"],
        "val_end": MODEL_CFG["split"]["val_end"],
    }
    if data_path is not None:
        tags["dataset_version"] = dataset_version(data_path)
    if extra:
        tags.update({k: str(v) for k, v in extra.items()})
    return tags


@contextmanager
def start_run(
    run_name: str,
    model_family: str,
    data_path: str | Path | None = None,
    extra_tags: dict[str, str] | None = None,
) -> Iterator[Any]:
    """Open an MLflow run with the standard tags already applied."""
    configure()
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tags(standard_tags(model_family, data_path, extra_tags))
        log.info("MLflow run %s (%s)", run_name, run.info.run_id[:8])
        yield run


def log_metrics_safe(metrics: dict[str, float]) -> None:
    """Log metrics, skipping NaN/inf which MLflow rejects."""
    import math

    clean = {
        k: float(v)
        for k, v in metrics.items()
        if isinstance(v, int | float) and math.isfinite(float(v))
    }
    dropped = set(metrics) - set(clean)
    if dropped:
        log.warning("Skipped non-finite metrics: %s", sorted(dropped))
    if clean:
        mlflow.log_metrics(clean)


def log_params_safe(params: dict[str, Any]) -> None:
    """Log params as strings; MLflow rejects some object types."""
    mlflow.log_params({k: str(v) for k, v in params.items() if v is not None})


def log_artifact_if_exists(path: str | Path, artifact_path: str | None = None) -> None:
    p = Path(path)
    if p.exists():
        mlflow.log_artifact(str(p), artifact_path=artifact_path)
    else:
        log.debug("Artifact not found, skipping: %s", p)


def verify_required_metrics(metrics: dict[str, float]) -> list[str]:
    """Return required metric names that are missing from a run.

    Called at the end of every training script so a member notices
    immediately if their run would be incomparable.
    """
    required = set(MODEL_CFG["metrics"]["required"])
    return sorted(required - set(metrics))


__all__ = [
    "configure",
    "start_run",
    "standard_tags",
    "git_commit",
    "git_dirty",
    "dataset_version",
    "log_metrics_safe",
    "log_params_safe",
    "log_artifact_if_exists",
    "verify_required_metrics",
]
