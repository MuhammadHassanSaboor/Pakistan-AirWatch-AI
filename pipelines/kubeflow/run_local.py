"""Execute the Kubeflow pipeline locally — no Kubeflow cluster required.

A full Kubeflow Pipelines install needs several GB of container images.
For development and for the course demo we use the KFP SDK's local
runner, which executes the SAME component definitions
(pipelines/kubeflow/components/) with the same typed inputs/outputs and
the same artifact hand-off between steps.

The local runner does not support `dsl.If`, so each governance gate is a
`require` step that FAILS the run when its check fails; every downstream
step depends on it. Same guarantee as the cluster pipeline: invalid data
never reaches training and a failing model never reaches registration.

    load_raw -> validate_data -> require(data-valid) -> engineer_features
      -> train_model -> evaluate_model -> require(quality-gate) -> register_model

Run inside Linux (the runner's `sh -c` launcher breaks on Windows paths):

    docker build -f docker/Dockerfile.kfp-local -t airwatch-kfp:local .
    docker run --rm -v "$PWD:/work" -w /work -e PYTHONPATH=/work \
        airwatch-kfp:local python pipelines/kubeflow/run_local.py --max-cities 8

Outputs (datasets, model, metrics) land in ./local_outputs/<run>/.
"""

# No `from __future__ import annotations`: KFP reads the component's type
# annotations at definition time and needs real types, not strings.
import argparse
import json
import sys
import time
from pathlib import Path

from kfp import dsl, local
from kfp.dsl import Dataset, Output

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from components import (
    engineer_features,
    evaluate_model,
    register_model,
    train_model,
    validate_data,
)
from components.common import BASE_IMAGE, DATA_PACKAGES


@dsl.component(base_image=BASE_IMAGE, packages_to_install=DATA_PACKAGES)
def load_raw(source_path: str, raw: Output[Dataset], max_cities: int = 0):
    """Entry step: bring the DVC-tracked raw parquet into the pipeline.

    On a cluster this role is played by `dsl.importer` reading from
    object storage; locally we copy from the working tree.
    """
    import pandas as pd

    df = pd.read_parquet(source_path)
    if max_cities:
        keep = df["city_id"].value_counts().index[:max_cities]
        df = df[df["city_id"].isin(keep)]
    df.to_parquet(raw.path, index=False)
    print(f"raw: {len(df):,} rows, {df['city_id'].nunique()} cities")


@dsl.component(base_image=BASE_IMAGE)
def require(passed: bool, gate: str):
    """Fail the run unless `passed`: the local stand-in for `dsl.If`."""
    if not passed:
        raise RuntimeError(f"Gate '{gate}' FAILED - downstream steps will not run")
    print(f"Gate '{gate}' passed")


@dsl.pipeline(name="pm25-training-pipeline-local")
def local_pipeline(
    source_path: str,
    max_cities: int = 8,
    n_estimators: int = 200,
    mae_threshold: float = 25.0,
    min_improvement_pct: float = 15.0,
):
    raw = load_raw(source_path=source_path, max_cities=max_cities)
    validation = validate_data(raw_dataset=raw.outputs["raw"], min_rows=1000)
    data_ok = require(passed=validation.outputs["Output"], gate="data-valid")

    features = engineer_features(raw_dataset=raw.outputs["raw"]).after(data_ok)
    training = train_model(
        train_set=features.outputs["train_set"],
        val_set=features.outputs["val_set"],
        n_estimators=n_estimators,
    )
    evaluation = evaluate_model(
        model=training.outputs["model"],
        test_set=features.outputs["test_set"],
        mae_threshold=mae_threshold,
        min_improvement_pct=min_improvement_pct,
    )
    gate_ok = require(passed=evaluation.outputs["Output"], gate="quality-gate")
    register_model(model=training.outputs["model"], stage="Staging").after(gate_ok)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the KFP pipeline locally")
    ap.add_argument(
        "--source",
        default=str(PROJECT_ROOT / "data" / "raw" / "airquality_hourly.parquet"),
    )
    ap.add_argument("--max-cities", type=int, default=8)
    ap.add_argument("--n-estimators", type=int, default=200)
    ap.add_argument("--mae-threshold", type=float, default=25.0)
    ap.add_argument("--min-improvement-pct", type=float, default=15.0)
    args = ap.parse_args()

    run_dir = PROJECT_ROOT / "local_outputs" / time.strftime("%Y%m%dT%H%M%S")
    # use_venv=False: run in the current interpreter, whose pinned
    # versions match the components' packages_to_install.
    local.init(
        runner=local.SubprocessRunner(use_venv=False), pipeline_root=str(run_dir)
    )

    t0 = time.time()
    summary: dict = {"run_dir": str(run_dir)}
    try:
        local_pipeline(
            source_path=args.source,
            max_cities=args.max_cities,
            n_estimators=args.n_estimators,
            mae_threshold=args.mae_threshold,
            min_improvement_pct=args.min_improvement_pct,
        )
        summary["status"] = "SUCCEEDED - model registered to Staging"
    except RuntimeError as exc:
        summary["status"] = f"STOPPED - {exc}"
    summary["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
