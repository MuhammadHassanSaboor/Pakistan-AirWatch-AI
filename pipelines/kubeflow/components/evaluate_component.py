"""Step D — held-out evaluation and the quality gate."""

from kfp import dsl
from kfp.dsl import Dataset, Input, Metrics, Model, Output

from .common import BASE_IMAGE, ML_PACKAGES


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
