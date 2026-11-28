"""Tests for champion/challenger promotion and the ETL warehouse load."""

from __future__ import annotations

import json
import os

import joblib
import numpy as np
import pandas as pd
import pytest

from src.data import load_db
from src.features.splits import chrono_split
from src.models import champion


class Constant:
    """A model that always predicts `value` — makes MAE fully predictable."""

    def __init__(self, value: float):
        self.value = value

    def predict(self, X):
        return np.full(len(X), self.value)


def _candidate(tmp_path, name, value, gate=True, features=("pm2_5",)):
    d = tmp_path / "candidates" / name
    d.mkdir(parents=True)
    joblib.dump(Constant(value), d / "model.pkl")
    (d / "metadata.json").write_text(
        json.dumps(
            {
                "run_name": name,
                "quality_gate_passed": gate,
                "feature_names": list(features),
                "metrics": {"test_mae": 1.0},
            }
        )
    )
    return d


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(champion, "PRODUCTION", tmp_path / "production")
    monkeypatch.setattr(champion, "ARCHIVE", tmp_path / "archive")
    return tmp_path


@pytest.fixture
def test_frame():
    return pd.DataFrame({"pm2_5": [50.0] * 10, "y": [50.0] * 10})


# ── champion / challenger ────────────────────────────────────────


def test_first_gated_candidate_is_promoted(isolated, test_frame):
    cand = _candidate(isolated, "a", 50.0)
    decision = champion.compare(cand, test_frame)
    assert decision["promote"] and decision["champion"] is None
    champion.promote(cand, decision)
    assert (champion.PRODUCTION / "model.pkl").exists()
    assert champion.status()["champion"] == "a"


def test_candidate_failing_gate_is_never_promoted(isolated, test_frame):
    cand = _candidate(isolated, "bad", 50.0, gate=False)
    assert champion.compare(cand, test_frame)["promote"] is False
    with pytest.raises(RuntimeError, match="quality gate"):
        champion.promote(cand)


def test_better_candidate_replaces_champion_and_old_one_is_archived(
    isolated, test_frame
):
    champion.promote(_candidate(isolated, "old", 40.0))  # MAE 10
    better = _candidate(isolated, "new", 49.0)  # MAE 1
    decision = champion.compare(better, test_frame)
    assert decision["promote"]
    assert decision["improvement_pct"] == pytest.approx(90.0)
    champion.promote(better, decision)
    assert champion.status()["champion"] == "new"
    assert champion.status()["archived_versions"] == 1


def test_marginally_better_candidate_is_rejected(isolated, test_frame):
    champion.promote(_candidate(isolated, "old", 40.0))  # MAE 10.0
    slightly = _candidate(isolated, "new", 40.1)  # MAE 9.9 -> 1% better, need 2%
    decision = champion.compare(slightly, test_frame)
    assert decision["promote"] is False
    assert "need" in decision["reason"]


def test_rollback_restores_previous_champion(isolated, test_frame):
    champion.promote(_candidate(isolated, "v1", 40.0))
    champion.promote(_candidate(isolated, "v2", 49.0))
    assert champion.rollback() == "v1"
    assert champion.status()["champion"] == "v1"


def test_rollback_without_archive_fails_loudly(isolated):
    with pytest.raises(RuntimeError, match="No archived model"):
        champion.rollback()


def test_compare_uses_a_real_trained_model(
    isolated, sample_features, feature_names, split_dates_for_sample, trained_model
):
    d = isolated / "candidates" / "lgb"
    d.mkdir(parents=True)
    joblib.dump(trained_model, d / "model.pkl")
    (d / "metadata.json").write_text(
        json.dumps(
            {
                "run_name": "lgb",
                "quality_gate_passed": True,
                "feature_names": feature_names,
            }
        )
    )
    _, _, test = chrono_split(sample_features, *split_dates_for_sample)
    decision = champion.compare(d, test)
    assert decision["candidate_mae"] > 0 and decision["promote"]


# ── ETL transform (no database needed) ───────────────────────────


def test_prepare_observations_dedups_and_types(sample_raw):
    doubled = pd.concat([sample_raw, sample_raw], ignore_index=True)
    out = load_db.prepare_observations(doubled)
    assert not out.duplicated(load_db.KEY).any()
    assert str(out["timestamp"].dt.tz) == "UTC"
    assert set(out.columns) <= set(load_db.OBS_COLUMNS)


def test_prepare_observations_requires_keys():
    with pytest.raises(ValueError, match="key columns"):
        load_db.prepare_observations(pd.DataFrame({"pm2_5": [1.0]}))


# ── ETL load (integration; runs only when a database is configured) ──


@pytest.mark.skipif(
    not os.getenv("AIRWATCH_TEST_DATABASE_URL"),
    reason="set AIRWATCH_TEST_DATABASE_URL to run the Postgres integration test",
)
def test_load_is_idempotent_against_postgres(sample_raw):
    engine = load_db.get_engine(os.environ["AIRWATCH_TEST_DATABASE_URL"])
    first = load_db.load_observations(sample_raw, engine=engine, source="test")
    second = load_db.load_observations(sample_raw, engine=engine, source="test")
    assert first["rows_in"] == second["rows_in"]
    stats = load_db.summary(engine)
    assert stats["observations"] >= first["rows_in"]
    back = load_db.extract_observations(engine)
    assert not back.duplicated(load_db.KEY).any()
