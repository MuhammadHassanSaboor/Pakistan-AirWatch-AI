"""Shared settings for every Kubeflow component.

Each component runs in its own pod built from `BASE_IMAGE`, so the
packages each step needs are pinned here once and reused.
"""

BASE_IMAGE = "python:3.11-slim"

DATA_PACKAGES = ["pandas==2.2.3", "pyarrow==17.0.0", "numpy==1.26.4"]
ML_PACKAGES = [*DATA_PACKAGES, "scikit-learn==1.5.2", "xgboost==2.1.1"]
REGISTRY_PACKAGES = ["mlflow-skinny==2.17.0"]
