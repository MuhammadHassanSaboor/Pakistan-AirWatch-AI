"""Step C — model training with early stopping on the validation split."""

from kfp import dsl
from kfp.dsl import Dataset, Input, Metrics, Model, Output

from .common import BASE_IMAGE, ML_PACKAGES


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

    exclude = {
        "y",
        "timestamp",
        "city_id",
        "city_name",
        "province",
        "data_source",
        "ingested_at",
        "valid_time",
    }
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
