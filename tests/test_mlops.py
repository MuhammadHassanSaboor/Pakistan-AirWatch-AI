"""Tests for the MLOps layer: tracking, registry governance, drift.

No MLflow server and no network. The MLflow client is stubbed, so
these verify *our* logic — the quality gate, the promotion rules, the
rollback selection — rather than MLflow's.

The governance tests are the important ones: they assert that a bad
model genuinely cannot reach production, which is the requirement the
whole registry exists to satisfy.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.models import registry, tracking
from src.monitoring import drift


# ──────────────────────────────────────────────────────────────
# Tracking helpers
# ──────────────────────────────────────────────────────────────
def test_git_commit_returns_a_short_sha_or_unknown():
    sha = tracking.git_commit()
    assert isinstance(sha, str)
    assert sha == "unknown" or 6 <= len(sha) <= 12


def test_git_dirty_returns_a_bool():
    assert isinstance(tracking.git_dirty(), bool)


def test_dataset_version_reads_the_dvc_md5(tmp_path):
    data = tmp_path / "features.parquet"
    (tmp_path / "features.parquet.dvc").write_text(
        "outs:\n- md5: abc123def456\n  size: 1234\n", encoding="utf-8"
    )
    assert tracking.dataset_version(data) == "abc123def456"


def test_dataset_version_reports_untracked_data(tmp_path):
    """An untracked dataset means the run is not reproducible."""
    assert tracking.dataset_version(tmp_path / "nothing.parquet") == "untracked"


def test_standard_tags_include_everything_the_comparison_needs(tmp_path):
    tags = tracking.standard_tags("xgboost", tmp_path / "x.parquet")
    for key in (
        "member",
        "model_family",
        "git_commit",
        "target",
        "horizons",
        "train_end",
        "val_end",
        "dataset_version",
    ):
        assert key in tags, f"runs must be tagged with {key}"
    assert tags["model_family"] == "xgboost"


def test_standard_tags_accept_extras():
    tags = tracking.standard_tags("ridge", extra={"alpha": 1.0})
    assert tags["alpha"] == "1.0"


def test_verify_required_metrics_spots_an_incomparable_run():
    """A run missing metrics cannot be compared against the others."""
    missing = tracking.verify_required_metrics({"test_mae": 10.0})
    assert "val_mae" in missing
    assert "baseline_mae" in missing


def test_verify_required_metrics_passes_a_complete_run():
    from src.config import MODEL_CFG

    complete = dict.fromkeys(MODEL_CFG["metrics"]["required"], 1.0)
    assert tracking.verify_required_metrics(complete) == []


def test_log_metrics_safe_drops_non_finite_values(monkeypatch):
    """MLflow rejects NaN and inf; dropping them must not lose the rest."""
    logged = {}
    monkeypatch.setattr(tracking.mlflow, "log_metrics", logged.update)

    tracking.log_metrics_safe(
        {
            "good": 1.5,
            "nan": float("nan"),
            "inf": float("inf"),
            "neg_inf": float("-inf"),
            "also_good": 2.0,
        }
    )
    assert set(logged) == {"good", "also_good"}


def test_log_params_safe_stringifies(monkeypatch):
    logged = {}
    monkeypatch.setattr(tracking.mlflow, "log_params", logged.update)
    tracking.log_params_safe({"depth": 8, "none": None, "lr": 0.05})
    assert logged == {"depth": "8", "lr": "0.05"}
    assert "none" not in logged


def test_log_artifact_if_exists_skips_missing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        tracking.mlflow, "log_artifact", lambda p, artifact_path=None: calls.append(p)
    )
    tracking.log_artifact_if_exists(tmp_path / "absent.png")
    assert calls == []

    present = tmp_path / "there.png"
    present.write_bytes(b"x")
    tracking.log_artifact_if_exists(present)
    assert len(calls) == 1


# ──────────────────────────────────────────────────────────────
# Registry: comparison
# ──────────────────────────────────────────────────────────────
def _fake_runs() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "run_id": ["r1", "r2", "r3", "r4"],
            "tags.member": ["hassan", "mudassar", "ifraz", "ifraz"],
            "tags.model_family": ["xgboost", "lightgbm", "ridge", "persistence"],
            "tags.quality_gate": ["pass", "pass", "fail", "fail"],
            "tags.mlflow.runName": ["xgb-1", "lgb-1", "ridge-1", "base-1"],
            "metrics.test_mae": [8.2, 8.9, 17.9, 14.0],
            "metrics.test_rmse": [15.3, 16.1, 28.1, 24.0],
            "metrics.test_r2": [0.80, 0.78, 0.61, 0.52],
            "metrics.mae_h1": [2.6, 2.9, 9.8, 6.9],
            "metrics.mae_h24": [10.7, 11.2, 25.0, 12.8],
            "metrics.baseline_mae": [14.0, 14.0, 14.0, 14.0],
            "metrics.improvement_pct": [41.3, 36.4, -27.8, 0.0],
            "metrics.train_seconds": [1688.0, 420.0, 30.0, 1.0],
        }
    )


def test_comparison_table_sorts_best_first(monkeypatch):
    monkeypatch.setattr(registry, "search_runs", lambda *_a, **_k: _fake_runs())
    table = registry.comparison_table()
    assert table.iloc[0]["model_family"] == "xgboost"
    assert table["test_mae"].is_monotonic_increasing


def test_comparison_table_renames_mlflow_columns(monkeypatch):
    monkeypatch.setattr(registry, "search_runs", lambda *_a, **_k: _fake_runs())
    table = registry.comparison_table()
    assert "member" in table.columns
    assert "tags.member" not in table.columns


def test_comparison_table_handles_no_runs(monkeypatch):
    monkeypatch.setattr(registry, "search_runs", lambda *_a, **_k: pd.DataFrame())
    assert registry.comparison_table().empty


def test_best_run_picks_the_lowest_test_mae(monkeypatch):
    monkeypatch.setattr(registry, "search_runs", lambda *_a, **_k: _fake_runs())
    best = registry.best_run()
    assert best["run_id"] == "r1"
    assert best["member"] == "hassan"


def test_best_run_returns_none_without_runs(monkeypatch):
    monkeypatch.setattr(registry, "search_runs", lambda *_a, **_k: pd.DataFrame())
    assert registry.best_run() is None


def test_best_run_ignores_runs_with_no_metric(monkeypatch):
    runs = _fake_runs()
    runs.loc[0, "metrics.test_mae"] = np.nan
    monkeypatch.setattr(registry, "search_runs", lambda *_a, **_k: runs)
    assert registry.best_run()["run_id"] == "r2"


# ──────────────────────────────────────────────────────────────
# Registry: governance
# ──────────────────────────────────────────────────────────────
class _Version:
    def __init__(self, version, stage, run_id, created=0):
        self.version = str(version)
        self.current_stage = stage
        self.run_id = run_id
        self.status = "READY"
        self.creation_timestamp = created


class _Run:
    def __init__(self, metrics):
        self.data = type("D", (), {"metrics": metrics, "tags": {}})()
        self.info = type("I", (), {"start_time": 0, "run_id": "x"})()


class _Client:
    """Minimal MLflow client stub recording the transitions requested."""

    def __init__(self, versions, metrics_by_run=None):
        self._versions = versions
        self._metrics = metrics_by_run or {}
        self.transitions = []
        self.tags = []

    def search_model_versions(self, _filter):
        return self._versions

    def get_model_version(self, _name, version):
        return next(v for v in self._versions if v.version == str(version))

    def get_run(self, run_id):
        return _Run(self._metrics.get(run_id, {}))

    def transition_model_version_stage(self, name, version, stage, **kwargs):
        self.transitions.append((name, str(version), stage, kwargs))

    def set_model_version_tag(self, _name, version, key, value):
        self.tags.append((str(version), key, value))


def _install_client(monkeypatch, client):
    monkeypatch.setattr(registry, "client", lambda: client)


def test_list_versions_is_newest_first(monkeypatch):
    client = _Client(
        [
            _Version(1, "Archived", "r1"),
            _Version(3, "Production", "r3"),
            _Version(2, "Staging", "r2"),
        ]
    )
    _install_client(monkeypatch, client)
    versions = registry.list_versions()
    assert [v["version"] for v in versions] == [3, 2, 1]


def test_production_version_finds_the_deployed_model(monkeypatch):
    client = _Client([_Version(1, "Archived", "r1"), _Version(2, "Production", "r2")])
    _install_client(monkeypatch, client)
    assert registry.production_version()["version"] == 2


def test_production_version_is_none_when_nothing_deployed(monkeypatch):
    _install_client(monkeypatch, _Client([_Version(1, "Staging", "r1")]))
    assert registry.production_version() is None


def test_promote_to_production_rejects_a_model_failing_the_gate(monkeypatch):
    """The core governance guarantee."""
    client = _Client(
        [_Version(5, "Staging", "bad")],
        {"bad": {"test_mae": 999.0, "improvement_pct": 1.0}},
    )
    _install_client(monkeypatch, client)
    monkeypatch.setattr(registry, "production_metrics", dict)

    with pytest.raises(RuntimeError, match="REJECTED"):
        registry.promote_to_production(5)

    assert client.transitions == [], "a rejected model must not be transitioned"


def test_promote_to_production_accepts_a_good_model(monkeypatch):
    client = _Client(
        [_Version(6, "Staging", "good")],
        {"good": {"test_mae": 8.2, "improvement_pct": 41.3}},
    )
    _install_client(monkeypatch, client)
    monkeypatch.setattr(registry, "production_metrics", dict)

    assert registry.promote_to_production(6) == 6
    name, version, stage, kwargs = client.transitions[0]
    assert version == "6"
    assert stage == "Production"
    assert kwargs["archive_existing_versions"] is True


def test_promote_to_production_rejects_a_candidate_no_better_than_live(monkeypatch):
    """Stops the pipeline churning production for noise."""
    client = _Client(
        [_Version(7, "Staging", "marginal")],
        {"marginal": {"test_mae": 8.19, "improvement_pct": 41.0}},
    )
    _install_client(monkeypatch, client)
    monkeypatch.setattr(registry, "production_metrics", lambda: {"test_mae": 8.2})

    with pytest.raises(RuntimeError, match="REJECTED"):
        registry.promote_to_production(7)
    assert client.transitions == []


def test_promotion_records_who_approved_it(monkeypatch):
    client = _Client(
        [_Version(8, "Staging", "good")],
        {"good": {"test_mae": 8.0, "improvement_pct": 42.0}},
    )
    _install_client(monkeypatch, client)
    monkeypatch.setattr(registry, "production_metrics", dict)

    registry.promote_to_production(8, approved_by="hassan")
    keys = {key: value for _v, key, value in client.tags}
    assert keys["approved_by"] == "hassan"
    assert "promoted_at" in keys


def test_rollback_restores_the_most_recent_archived_version(monkeypatch):
    client = _Client(
        [
            _Version(1, "Archived", "r1"),
            _Version(2, "Archived", "r2"),
            _Version(3, "Production", "r3"),
        ]
    )
    _install_client(monkeypatch, client)

    assert registry.rollback() == 2, "must restore v2, not the older v1"
    assert client.transitions[0][2] == "Production"


def test_rollback_fails_clearly_with_nothing_to_restore(monkeypatch):
    _install_client(monkeypatch, _Client([_Version(1, "Production", "r1")]))
    with pytest.raises(RuntimeError, match="No archived version"):
        registry.rollback()


def test_version_for_run_errors_helpfully(monkeypatch):
    _install_client(monkeypatch, _Client([_Version(1, "None", "other")]))
    with pytest.raises(ValueError, match="No registered model version"):
        registry._version_for_run("missing-run")


# ──────────────────────────────────────────────────────────────
# Drift detection
# ──────────────────────────────────────────────────────────────
def test_psi_is_near_zero_for_identical_distributions():
    rng = np.random.default_rng(0)
    values = pd.Series(rng.normal(50, 10, 5000))
    assert drift._psi(values, values) < 0.01


def test_psi_detects_a_shifted_distribution():
    rng = np.random.default_rng(0)
    reference = pd.Series(rng.normal(50, 10, 5000))
    shifted = pd.Series(rng.normal(150, 10, 5000))
    assert drift._psi(reference, shifted) > 0.25


def test_psi_returns_zero_for_tiny_samples():
    """Too few points to say anything; claiming drift would be noise."""
    assert drift._psi(pd.Series([1.0, 2.0]), pd.Series([3.0, 4.0])) == 0.0


def test_psi_handles_nulls():
    rng = np.random.default_rng(1)
    reference = pd.Series(rng.normal(0, 1, 1000))
    current = pd.Series([*rng.normal(0, 1, 1000), *([np.nan] * 50)])
    assert drift._psi(reference, current) < 0.1


def test_drift_check_flags_a_smog_season_shift(tmp_path):
    """A physically coherent shift must trigger retraining."""
    rng = np.random.default_rng(42)
    n = 3000
    reference = pd.DataFrame(
        {
            "pm2_5": rng.gamma(4, 15, n),
            "pm10": rng.gamma(5, 25, n),
            "temperature_2m": rng.normal(28, 4, n),
            "wind_speed_10m": rng.gamma(2, 3, n),
        }
    )
    current = reference.copy()
    current["pm2_5"] *= 3.5
    current["pm10"] *= 3.0
    current["temperature_2m"] -= 12
    current["wind_speed_10m"] *= 0.4

    result = drift.run_drift_check(
        reference=reference, current=current, out_dir=tmp_path
    )
    assert result["drift_share"] > drift.DRIFT_THRESHOLD
    assert result["retrain_recommended"] is True
    assert (tmp_path / "drift_report.json").exists()


def test_drift_check_is_quiet_when_nothing_changed(tmp_path):
    rng = np.random.default_rng(7)
    n = 3000
    reference = pd.DataFrame(
        {"pm2_5": rng.gamma(4, 15, n), "temperature_2m": rng.normal(25, 5, n)}
    )
    current = pd.DataFrame(
        {"pm2_5": rng.gamma(4, 15, n), "temperature_2m": rng.normal(25, 5, n)}
    )
    result = drift.run_drift_check(
        reference=reference, current=current, out_dir=tmp_path
    )
    assert result["retrain_recommended"] is False


def test_drift_check_reports_psi_per_feature(tmp_path):
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"pm2_5": rng.gamma(4, 15, 2000)})
    result = drift.run_drift_check(
        reference=frame, current=frame.copy(), out_dir=tmp_path
    )
    assert "pm2_5" in result["psi"]


def test_drift_check_rejects_non_overlapping_columns(tmp_path):
    with pytest.raises(ValueError, match="No monitored columns"):
        drift.run_drift_check(
            reference=pd.DataFrame({"a": [1, 2, 3]}),
            current=pd.DataFrame({"b": [1, 2, 3]}),
            out_dir=tmp_path,
        )


def test_drift_report_is_json_serialisable(tmp_path):
    rng = np.random.default_rng(5)
    frame = pd.DataFrame({"pm2_5": rng.gamma(4, 15, 1500)})
    drift.run_drift_check(reference=frame, current=frame.copy(), out_dir=tmp_path)
    payload = json.loads((tmp_path / "drift_report.json").read_text(encoding="utf-8"))
    assert "drift_share" in payload
    assert "generated_at" in payload
