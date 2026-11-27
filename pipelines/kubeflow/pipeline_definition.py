"""Kubeflow Pipelines definition for the PM2.5 training workflow.

Each stage is a separate containerised component with its own CPU and
memory limits, and artifacts flow between them as typed inputs and
outputs. That is the difference from the Airflow DAG: Airflow decides
*whether* to train, Kubeflow decides *how* the training graph runs and
isolates each step.

Two conditional branches implement the governance requirement:

    if data is valid        -> proceed to feature engineering
    if the gate passes      -> register the model

A model that fails evaluation simply never reaches the register step,
so there is no code path by which a bad model becomes a candidate.

Compile
-------
    python pipelines/kubeflow/pipeline_definition.py

Run
---
    kubectl port-forward -n kubeflow svc/ml-pipeline-ui 8080:80
    # upload compiled_pipeline.yaml in the UI, or:
    python pipelines/kubeflow/pipeline_definition.py --submit

Components live in `components/`, one module per step, so each can be
reused or tested on its own.
"""

import argparse
import sys
from pathlib import Path

from kfp import compiler, dsl

sys.path.insert(0, str(Path(__file__).parent))

from components import (
    engineer_features,
    evaluate_model,
    register_model,
    train_model,
    validate_data,
)

OUT_PATH = Path(__file__).parent / "compiled_pipeline.yaml"


# ──────────────────────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────────────────────
@dsl.pipeline(
    name="pm25-training-pipeline",
    description="Pakistan AirWatch AI — validate, engineer, train, gate, register",
)
def pm25_pipeline(
    raw_uri: str = "gs://airwatch/airquality_hourly.parquet",
    mae_threshold: float = 25.0,
    min_improvement_pct: float = 15.0,
    max_depth: int = 8,
    learning_rate: float = 0.05,
    n_estimators: int = 400,
    tracking_uri: str = "",
):
    raw = dsl.importer(
        artifact_uri=raw_uri,
        artifact_class=dsl.Dataset,
        reimport=False,
    )

    validation = validate_data(raw_dataset=raw.output)
    validation.set_cpu_limit("1").set_memory_limit("2G")

    # Branch 1: nothing downstream runs on invalid data.
    with dsl.If(validation.outputs["Output"] == True, name="data-is-valid"):  # noqa: E712
        features = engineer_features(raw_dataset=raw.output)
        features.set_cpu_limit("2").set_memory_limit("8G")

        training = train_model(
            train_set=features.outputs["train_set"],
            val_set=features.outputs["val_set"],
            max_depth=max_depth,
            learning_rate=learning_rate,
            n_estimators=n_estimators,
        )
        training.set_cpu_limit("4").set_memory_limit("8G")

        evaluation = evaluate_model(
            model=training.outputs["model"],
            test_set=features.outputs["test_set"],
            mae_threshold=mae_threshold,
            min_improvement_pct=min_improvement_pct,
        )
        evaluation.set_cpu_limit("2").set_memory_limit("4G")

        # Branch 2: the quality gate. A failing model never registers.
        with dsl.If(evaluation.outputs["Output"] == True, name="passes-quality-gate"):  # noqa: E712
            register_model(
                model=training.outputs["model"],
                stage="Staging",
                tracking_uri=tracking_uri,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile the Kubeflow pipeline")
    parser.add_argument("--submit", action="store_true",
                        help="submit a run after compiling")
    parser.add_argument("--host", default="http://localhost:8080")
    parser.add_argument("--raw-uri", default="gs://airwatch/airquality_hourly.parquet")
    args = parser.parse_args()

    compiler.Compiler().compile(pm25_pipeline, str(OUT_PATH))
    print(f"Compiled -> {OUT_PATH}")

    if args.submit:
        import kfp

        client = kfp.Client(host=args.host)
        run = client.create_run_from_pipeline_package(
            str(OUT_PATH),
            arguments={"raw_uri": args.raw_uri},
            experiment_name="airwatch-training",
        )
        print(f"Submitted run: {run.run_id}")


if __name__ == "__main__":
    main()
