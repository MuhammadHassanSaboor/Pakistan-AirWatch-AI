# Pakistan AirWatch AI — ML pipeline base image
#
# One image for every training-side step: ingestion, validation,
# feature engineering, training and evaluation. Used by
#   * Kubeflow component pods (set BASE_IMAGE in components/common.py)
#   * Airflow tasks that run the pipeline in a container
#   * anyone reproducing a training run without a local Python setup
#
#   docker build -f docker/Dockerfile.ml -t airwatch-ml .
#   docker run --rm -v "$PWD/data:/app/data" -v "$PWD/models:/app/models" \
#       --env-file .env airwatch-ml python -m src.models.train_xgboost
#
# No data, models or secrets are baked in: data and models are mounted,
# credentials come from --env-file at run time.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp: OpenMP runtime for XGBoost / LightGBM. git: lets MLflow and
# DVC record the commit a run came from.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 mluser

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=mluser:mluser src/              src/
COPY --chown=mluser:mluser configs/          configs/
COPY --chown=mluser:mluser data/reference/   data/reference/
COPY --chown=mluser:mluser dvc.yaml pyproject.toml ./

RUN mkdir -p data/raw data/processed models reports \
    && chown -R mluser:mluser /app

USER mluser

CMD ["python", "-m", "src.models.train_xgboost", "--help"]
