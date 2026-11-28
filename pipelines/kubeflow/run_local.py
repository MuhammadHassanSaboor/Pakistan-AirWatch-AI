"""Execute the Kubeflow pipeline components locally — no cluster required.

A full Kubeflow Pipelines install needs several GB of container images
and a multi-node-sized cluster. For development and for the course demo
we use the KFP SDK's local runner, which executes the SAME component
definitions (pipelines/kubeflow/components/) as subprocesses, with the
same typed inputs and outputs and the same artifact hand-off between
steps. The two governance gates of the compiled pipeline are applied
here as ordinary conditionals:

    load_raw -> validate_data --(valid?)--> engineer_features
             -> train_model -> evaluate_model --(gate?)--> register_model

Outputs (datasets, model, metrics) land in ./local_outputs/<run>/.

    python pipelines/kubeflow/run_local.py
    python pipelines/kubeflow/run_local.py --max-cities 6 --n-estimators 150
"""

from __future__ import annotations

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


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the KFP components locally")
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

    summary: dict = {"run_dir": str(run_dir)}
    t0 = time.time()

    raw = load_raw(source_path=args.source, max_cities=args.max_cities)
    validation = validate_data(raw_dataset=raw.outputs["raw"], min_rows=1000)
    summary["data_valid"] = bool(validation.output)

    if not validation.output:
        summary["stopped_at"] = "validate_data"
    else:
        features = engineer_features(raw_dataset=raw.outputs["raw"])
        training = train_model(
            train_set=features.outputs["train_set"],
            val_set=features.outputs["val_set"],
            n_estimators=args.n_estimators,
        )
        evaluation = evaluate_model(
            model=training.outputs["model"],
            test_set=features.outputs["test_set"],
            mae_threshold=args.mae_threshold,
            min_improvement_pct=args.min_improvement_pct,
        )
        summary["quality_gate_passed"] = bool(evaluation.output)
        if evaluation.output:
            register_model(model=training.outputs["model"], stage="Staging")
            summary["registered"] = True
        else:
            summary["stopped_at"] = "evaluate_model"
            summary["registered"] = False

    summary["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
