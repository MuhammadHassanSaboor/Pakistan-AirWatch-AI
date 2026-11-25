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
"""

import argparse
from pathlib import Path

from kfp import compiler, dsl
from kfp.dsl import Dataset, Input, Metrics, Model, Output

BASE_IMAGE = "python:3.11-slim"
OUT_PATH = Path(__file__).parent / "compiled_pipeline.yaml"

DATA_PACKAGES = ["pandas==2.2.3", "pyarrow==17.0.0", "numpy==1.26.4"]
ML_PACKAGES = [*DATA_PACKAGES, "scikit-learn==1.5.2", "xgboost==2.1.1"]


# ──────────────────────────────────────────────────────────────
# Step A: validation
# ──────────────────────────────────────────────────────────────
@dsl.component(base_image=BASE_IMAGE, packages_to_install=DATA_PACKAGES)
def validate_data(
    raw_dataset: Input[Dataset],
    report: Output[Metrics],
    min_rows: int = 10000,
) -> bool:
    """Schema and completeness checks. Returns False to halt the graph."""
    import pandas as pd

    df = pd.read_parquet(raw_dataset.path)

    checks = {
        "has_minimum_rows": len(df) >= min_rows,
        "has_target": "pm2_5" in df.columns,
        "no_duplicate_keys": not df.duplicated(["city_id", "timestamp"]).any(),
        "target_mostly_present": df["pm2_5"].isna().mean() < 0.30
        if "pm2_5" in df.columns
        else False,
        "coords_in_pakistan": bool(
            df["latitude"].between(23.0, 37.5).all()
            and df["longitude"].between(60.0, 78.0).all()
        )
        if {"latitude", "longitude"} <= set(df.columns)
        else False,
    }

    for name, passed in checks.items():
        report.log_metric(name, 1.0 if passed else 0.0)
    report.log_metric("rows", float(len(df)))
    report.log_metric("cities", float(df["city_id"].nunique()))

    ok = all(checks.values())
    print(f"Validation checks: {checks}")
    print(f"Overall: {'PASS' if ok else 'FAIL'}")
    return ok


# ──────────────────────────────────────────────────────────────
# Step B: feature engineering and splitting
# ──────────────────────────────────────────────────────────────
@dsl.component(base_image=BASE_IMAGE, packages_to_install=DATA_PACKAGES)
def engineer_features(
    raw_dataset: Input[Dataset],
    train_set: Output[Dataset],
    val_set: Output[Dataset],
    test_set: Output[Dataset],
    stats: Output[Metrics],
    train_end: str = "2025-05-31T23:00:00Z",
    val_end: str = "2025-12-31T23:00:00Z",
    horizons: str = "1,6,12,24",
):
    """Lags, calendar and weather features, then a chronological split."""
    import numpy as np
    import pandas as pd

    df = pd.read_parquet(raw_dataset.path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(["city_id", "timestamp"]).reset_index(drop=True)

    # Calendar
    ts = df["timestamp"]
    df["hour"] = ts.dt.hour
    df["day_of_week"] = ts.dt.dayofweek
    df["month"] = ts.dt.month
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["is_smog_season"] = df["month"].isin([10, 11, 12, 1]).astype(int)

    # Lags — past information only.
    grouped = df.groupby("city_id", sort=False)["pm2_5"]
    for lag in (1, 3, 6, 12, 24, 48, 168):
        df[f"pm2_5_lag_{lag}h"] = grouped.shift(lag)
    shifted = grouped.shift(1)
    for window in (6, 24, 72):
        df[f"pm2_5_roll{window}_mean"] = (
            shifted.groupby(df["city_id"], sort=False)
            .rolling(window, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )

    if {"wind_speed_10m", "boundary_layer_height"} <= set(df.columns):
        df["ventilation_index"] = df["wind_speed_10m"] * df[
            "boundary_layer_height"
        ].fillna(500)

    # Supervised reshape
    frames = []
    for h in [int(x) for x in horizons.split(",")]:
        part = df.copy()
        part["horizon"] = h
        part["y"] = part.groupby("city_id", sort=False)["pm2_5"].shift(-h)
        frames.append(part)
    out = pd.concat(frames, ignore_index=True).dropna(subset=["y"])
    out = out.dropna(subset=["pm2_5_lag_1h"])

    # Chronological split
    stamps = pd.to_datetime(out["timestamp"], utc=True)
    train = out[stamps <= pd.Timestamp(train_end)]
    val = out[
        (stamps > pd.Timestamp(train_end)) & (stamps <= pd.Timestamp(val_end))
    ]
    test = out[stamps > pd.Timestamp(val_end)]

    train.to_parquet(train_set.path, index=False)
    val.to_parquet(val_set.path, index=False)
    test.to_parquet(test_set.path, index=False)

    stats.log_metric("train_rows", float(len(train)))
    stats.log_metric("val_rows", float(len(val)))
    stats.log_metric("test_rows", float(len(test)))
    print(f"train={len(train):,} val={len(val):,} test={len(test):,}")


# ──────────────────────────────────────────────────────────────
# Step C: training
# ──────────────────────────────────────────────────────────────
@dsl.component(base_image=BASE_IMAGE, packages_to_install=ML_PACKAGES)
def train_model(
    train_set: Input[Dataset],
    val_set: Input[Dataset],
    model: Output[Model],
    metrics: Output[Metrics],
    max_depth: int = 8,
    learning_rate: float = 0.05,
    n_estimators: int = 400,
):
    """Train XGBoost with early stopping on the validation split."""
    import json
    import time

    import pandas as pd
    import xgboost as xgb
    from sklearn.metrics import mean_absolute_error

    train = pd.read_parquet(train_set.path)
    val = pd.read_parquet(val_set.path)

    exclude = {"y", "timestamp", "city_id", "city_name", "province",
               "data_source", "ingested_at", "valid_time"}
    features = [
        c
        for c in train.columns
        if c not in exclude and pd.api.types.is_numeric_dtype(train[c])
    ]

    estimator = xgb.XGBRegressor(
        objective="reg:absoluteerror",
        tree_method="hist",
        max_depth=max_depth,
        learning_rate=learning_rate,
        n_estimators=n_estimators,
        subsample=0.8,
        colsample_bytree=0.8,
        early_stopping_rounds=50,
        random_state=42,
    )

    started = time.time()
    estimator.fit(
        train[features],
        train["y"],
        eval_set=[(val[features], val["y"])],
        verbose=False,
    )
    elapsed = time.time() - started

    val_mae = mean_absolute_error(val["y"], estimator.predict(val[features]))

    estimator.save_model(f"{model.path}.json")
    with open(f"{model.path}.features.json", "w") as handle:
        json.dump(features, handle)

    metrics.log_metric("val_mae", float(val_mae))
    metrics.log_metric("train_seconds", float(elapsed))
    metrics.log_metric("n_features", float(len(features)))
    print(f"val MAE={val_mae:.3f} in {elapsed:.1f}s over {len(features)} features")


# ──────────────────────────────────────────────────────────────
# Step D: evaluation and the quality gate
# ──────────────────────────────────────────────────────────────
@dsl.component(base_image=BASE_IMAGE, packages_to_install=ML_PACKAGES)
def evaluate_model(
    model: Input[Model],
    test_set: Input[Dataset],
    metrics: Output[Metrics],
    mae_threshold: float = 25.0,
    min_improvement_pct: float = 15.0,
) -> bool:
    """Score on the held-out test set and apply the gate.

    Returns False when the candidate is not good enough. The pipeline
    uses that to skip registration entirely.
    """
    import json

    import numpy as np
    import pandas as pd
    import xgboost as xgb
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    test = pd.read_parquet(test_set.path)
    with open(f"{model.path}.features.json") as handle:
        features = json.load(handle)

    estimator = xgb.XGBRegressor()
    estimator.load_model(f"{model.path}.json")

    predictions = np.clip(estimator.predict(test[features]), 0, None)

    mae = float(mean_absolute_error(test["y"], predictions))
    rmse = float(np.sqrt(mean_squared_error(test["y"], predictions)))
    r2 = float(r2_score(test["y"], predictions))

    baseline = test["pm2_5_lag_1h"].fillna(test["y"].median())
    baseline_mae = float(mean_absolute_error(test["y"], baseline))
    improvement = 100.0 * (baseline_mae - mae) / baseline_mae

    metrics.log_metric("test_mae", mae)
    metrics.log_metric("test_rmse", rmse)
    metrics.log_metric("test_r2", r2)
    metrics.log_metric("baseline_mae", baseline_mae)
    metrics.log_metric("improvement_pct", improvement)

    for horizon in sorted(test["horizon"].unique()):
        mask = (test["horizon"] == horizon).to_numpy()
        metrics.log_metric(
            f"mae_h{int(horizon)}",
            float(mean_absolute_error(test.loc[mask, "y"], predictions[mask])),
        )

    passed = mae <= mae_threshold and improvement >= min_improvement_pct
    metrics.log_metric("quality_gate_passed", 1.0 if passed else 0.0)

    print(f"test MAE  : {mae:.3f} (limit {mae_threshold})")
    print(f"baseline  : {baseline_mae:.3f}")
    print(f"improvement: {improvement:.1f}% (minimum {min_improvement_pct}%)")
    print(f"QUALITY GATE: {'PASS' if passed else 'FAIL'}")
    return passed


# ──────────────────────────────────────────────────────────────
# Step E: registration
# ──────────────────────────────────────────────────────────────
@dsl.component(base_image=BASE_IMAGE, packages_to_install=["mlflow-skinny==2.17.0"])
def register_model(
    model: Input[Model],
    model_name: str = "pm25-forecaster",
    stage: str = "Staging",
    tracking_uri: str = "",
):
    """Register the approved candidate. Only reachable via the gate."""
    print(f"Registering {model_name} from {model.path} into stage={stage}")
    if not tracking_uri:
        print("No tracking URI supplied; registration is a no-op in this run.")
        return
    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    print(f"Would register against {tracking_uri}")


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
