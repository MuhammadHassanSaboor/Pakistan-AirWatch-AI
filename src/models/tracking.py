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
    what makes "reproduce run 42" a real operation.
    """
    dvc_file = Path(f"{path}.dvc")
    if not dvc_file.is_absolute():
        dvc_file = PROJECT_ROOT / dvc_file
    if not dvc_file.exists():
        return "untracked"
    try:
        for line in dvc_file.read_text(encoding="utf-8").splitlines():
            if "md5:" in line:
                return line.split("md5:")[1].strip()
    except Exception:
        pass
    return "unknown"


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
