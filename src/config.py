"""Central configuration loader.

Every module reads settings through this file so that split dates,
thresholds and paths are defined exactly once. Nothing anywhere else
hard-codes a date or a threshold.

Usage
-----
    from src.config import DATA_CFG, MODEL_CFG, PROJECT_ROOT, settings

    start = DATA_CFG["time"]["air_quality_start"]
    gate = MODEL_CFG["quality_gate"]["max_test_mae"]
    uri = settings.mlflow_tracking_uri
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "configs"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
MODELS_DIR = PROJECT_ROOT / "models"

# Load .env once, if present. Missing .env is fine — every value
# below has a safe default, so the project runs out of the box.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Config file missing: {path}\n"
            "Run from the project root, or restore the file from git."
        )
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


DATA_CFG: dict[str, Any] = _load_yaml("data_config.yaml")
MODEL_CFG: dict[str, Any] = _load_yaml("model_params.yaml")


def resolve(path_like: str | Path) -> Path:
    """Turn a config-relative path into an absolute path."""
    p = Path(path_like)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings sourced from environment variables.

    Secrets live ONLY here, read from the environment. They are never
    written to a YAML file, never logged, and never committed — this
    repository is public.
    """

    # MLflow / DagsHub
    mlflow_tracking_uri: str = field(
        default_factory=lambda: os.getenv("MLFLOW_TRACKING_URI", "")
    )
    mlflow_username: str = field(
        default_factory=lambda: os.getenv("MLFLOW_TRACKING_USERNAME", "")
    )
    mlflow_password: str = field(
        default_factory=lambda: os.getenv("MLFLOW_TRACKING_PASSWORD", "")
    )
    mlflow_experiment: str = field(
        default_factory=lambda: os.getenv("MLFLOW_EXPERIMENT_NAME", "pm25-forecasting")
    )
    member: str = field(
        default_factory=lambda: os.getenv("AIRWATCH_MEMBER", "unknown").lower()
    )

    # Data sources
    openaq_api_key: str = field(default_factory=lambda: os.getenv("OPENAQ_API_KEY", ""))

    # API
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: int(os.getenv("API_PORT", "5000")))
    app_version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "0.1.0"))
    allowed_origins: str = field(
        default_factory=lambda: os.getenv(
            "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
        )
    )

    # Model loading
    model_source: str = field(
        default_factory=lambda: os.getenv("MODEL_SOURCE", "local").lower()
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("MODEL_NAME", "pm25-forecaster")
    )
    model_stage: str = field(
        default_factory=lambda: os.getenv("MODEL_STAGE", "Production")
    )
    local_model_path: str = field(
        default_factory=lambda: os.getenv("LOCAL_MODEL_PATH", "models/production")
    )

    # Database
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "postgresql://{u}:{p}@{h}:{port}/{db}".format(
                u=os.getenv("POSTGRES_USER", "airwatch"),
                p=os.getenv("POSTGRES_PASSWORD", ""),
                h=os.getenv("POSTGRES_HOST", "localhost"),
                port=os.getenv("POSTGRES_PORT", "5432"),
                db=os.getenv("POSTGRES_DB", "airwatch"),
            ),
        )
    )

    @property
    def mlflow_configured(self) -> bool:
        """True when we have enough credentials to reach DagsHub."""
        return bool(
            self.mlflow_tracking_uri and self.mlflow_username and self.mlflow_password
        )

    @property
    def openaq_enabled(self) -> bool:
        """OpenAQ is strictly optional; without a key we skip it."""
        return bool(self.openaq_api_key.strip()) and bool(
            DATA_CFG.get("openaq", {}).get("enabled", False)
        )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    def redacted(self) -> dict[str, Any]:
        """Safe-to-log view. Secrets become 'set' or 'not set'."""
        return {
            "mlflow_tracking_uri": self.mlflow_tracking_uri or "not set",
            "mlflow_username": "set" if self.mlflow_username else "not set",
            "mlflow_password": "set" if self.mlflow_password else "not set",
            "mlflow_experiment": self.mlflow_experiment,
            "member": self.member,
            "openaq_api_key": "set" if self.openaq_api_key else "not set",
            "model_source": self.model_source,
            "model_name": self.model_name,
            "model_stage": self.model_stage,
            "app_version": self.app_version,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


# ──────────────────────────────────────────────────────────────
# Convenience accessors used across the codebase
# ──────────────────────────────────────────────────────────────
def split_dates() -> tuple[str, str]:
    """(train_end, val_end) — the single source of truth."""
    s = MODEL_CFG["split"]
    return s["train_end"], s["val_end"]


def quality_gate() -> dict[str, float]:
    return MODEL_CFG["quality_gate"]


def feature_exclusions() -> list[str]:
    return list(MODEL_CFG["features"]["exclude"])


def horizons() -> list[int]:
    return list(MODEL_CFG["horizons"])


__all__ = [
    "DATA_CFG",
    "MODEL_CFG",
    "PROJECT_ROOT",
    "DATA_DIR",
    "REPORTS_DIR",
    "MODELS_DIR",
    "Settings",
    "settings",
    "get_settings",
    "resolve",
    "split_dates",
    "quality_gate",
    "feature_exclusions",
    "horizons",
]
