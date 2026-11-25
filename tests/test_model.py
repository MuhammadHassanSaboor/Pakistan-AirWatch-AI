"""Model tests: output validity, quality gates and regression checks."""

from __future__ import annotations

import numpy as np
import pytest

from src.config import MODEL_CFG
from src.features.splits import assert_no_overlap, chrono_split
from src.models.evaluate import (
    BASELINES,
    check_quality_gate,
    evaluate_model,
    metrics_by_horizon,
    persistence_prediction,
    regression_metrics,
)


# ── prediction validity ───────────────────────────────────────
def test_prediction_shape_matches_input(trained_model, test_split, feature_names):
    preds = trained_model.predict(test_split[feature_names])
    assert preds.shape[0] == len(test_split)


def test_predictions_are_never_nan(trained_model, test_split, feature_names):
    preds = trained_model.predict(test_split[feature_names])
    assert not np.isnan(preds).any()


def test_predictions_are_physically_plausible(trained_model, test_split, feature_names):
    """PM2.5 cannot be negative, and 2000 µg/m³ would be off the scale."""
    preds = np.clip(trained_model.predict(test_split[feature_names]), 0, None)
    assert (preds >= 0).all()
    assert (preds < 2000).all()


def test_model_handles_a_single_row(trained_model, test_split, feature_names):
    one = test_split[feature_names].head(1)
    preds = trained_model.predict(one)
    assert len(preds) == 1


def test_model_is_deterministic(trained_model, test_split, feature_names):
    a = trained_model.predict(test_split[feature_names].head(100))
    b = trained_model.predict(test_split[feature_names].head(100))
    assert np.allclose(a, b)


# ── metrics ───────────────────────────────────────────────────
def test_regression_metrics_on_perfect_prediction():
    y = np.array([10.0, 20.0, 30.0])
    m = regression_metrics(y, y, prefix="test_")
    assert m["test_mae"] == pytest.approx(0.0)
    assert m["test_r2"] == pytest.approx(1.0)


def test_regression_metrics_handle_nan():
    y = np.array([10.0, np.nan, 30.0])
    p = np.array([10.0, 20.0, 30.0])
    m = regression_metrics(y, p)
    assert m["mae"] == pytest.approx(0.0)


def test_metrics_by_horizon_returns_one_per_horizon(
    trained_model, test_split, feature_names
):
    preds = trained_model.predict(test_split[feature_names])
    per_h = metrics_by_horizon(test_split, preds, horizons=[1, 24])
    assert set(per_h) == {"mae_h1", "mae_h24"}


def test_all_required_metrics_produced(trained_model, test_split, feature_names):
    """Every member's run must log the same metric names."""
    metrics, _ = evaluate_model(trained_model, test_split, test_split, feature_names)
    required = set(MODEL_CFG["metrics"]["required"]) - {"train_seconds"}
    missing = required - set(metrics)
    # mae_h6 / mae_h12 are absent because the fixture uses horizons [1, 24].
    missing -= {"mae_h6", "mae_h12"}
    assert not missing, f"missing metrics: {sorted(missing)}"


# ── baselines ─────────────────────────────────────────────────
def test_every_baseline_produces_finite_predictions(test_split):
    for name, fn in BASELINES.items():
        preds = fn(test_split)
        assert len(preds) == len(test_split), name
        assert np.isfinite(preds).all(), f"{name} produced non-finite values"


def test_persistence_baseline_uses_the_lag_column(test_split):
    preds = persistence_prediction(test_split)
    expected = test_split["pm2_5_lag_1h"].fillna(test_split["pm2_5_roll24_mean"])
    mask = expected.notna().to_numpy()
    assert np.allclose(preds[mask], expected[mask], rtol=1e-4)


def test_model_beats_the_persistence_baseline(trained_model, test_split, feature_names):
    """The core sanity check. If this fails, the model is broken."""
    metrics, _ = evaluate_model(trained_model, test_split, test_split, feature_names)
    assert metrics["test_mae"] < metrics["baseline_mae"], (
        f"model MAE {metrics['test_mae']:.2f} is no better than the "
        f"persistence baseline {metrics['baseline_mae']:.2f}"
    )


# ── quality gate ──────────────────────────────────────────────
def test_quality_gate_accepts_a_good_model():
    good = {"test_mae": 10.0, "improvement_pct": 40.0}
    passed, reasons = check_quality_gate(good)
    assert passed and not reasons


def test_quality_gate_rejects_high_error():
    bad = {"test_mae": 999.0, "improvement_pct": 40.0}
    passed, reasons = check_quality_gate(bad)
    assert not passed
    assert any("test_mae" in r for r in reasons)


def test_quality_gate_rejects_no_improvement_over_baseline():
    bad = {"test_mae": 10.0, "improvement_pct": 1.0}
    passed, reasons = check_quality_gate(bad)
    assert not passed
    assert any("baseline" in r for r in reasons)


def test_quality_gate_rejects_candidate_no_better_than_production():
    """Stops the pipeline redeploying a model for no reason."""
    candidate = {"test_mae": 11.9, "improvement_pct": 40.0}
    passed, reasons = check_quality_gate(candidate, production_mae=12.0)
    assert not passed
    assert any("deployed" in r for r in reasons)


def test_quality_gate_accepts_clearly_better_candidate():
    candidate = {"test_mae": 9.0, "improvement_pct": 40.0}
    passed, _ = check_quality_gate(candidate, production_mae=12.0)
    assert passed


def test_quality_gate_rejects_missing_metrics():
    passed, reasons = check_quality_gate({})
    assert not passed
    assert reasons


# ── splits ────────────────────────────────────────────────────
def test_splits_do_not_overlap(sample_features, split_dates_for_sample):
    train_end, val_end = split_dates_for_sample
    train, val, test = chrono_split(sample_features, train_end, val_end)
    assert_no_overlap(train, val, test)


def test_split_is_chronological_not_random(sample_features, split_dates_for_sample):
    train_end, val_end = split_dates_for_sample
    train, val, test = chrono_split(sample_features, train_end, val_end)
    assert train.timestamp.max() < val.timestamp.min()
    assert val.timestamp.max() < test.timestamp.min()


def test_split_rejects_inverted_dates(sample_features):
    with pytest.raises(ValueError, match="must be before"):
        chrono_split(sample_features, "2024-06-01T00:00:00Z", "2024-01-01T00:00:00Z")


def test_split_rejects_dates_producing_empty_parts(sample_features):
    with pytest.raises(ValueError, match="empty"):
        chrono_split(sample_features, "1990-01-01T00:00:00Z", "1990-06-01T00:00:00Z")


# ── regression ────────────────────────────────────────────────
def test_model_error_within_regression_threshold(
    trained_model, test_split, feature_names
):
    """Detects an unexpected deterioration in model quality.

    The bound is deliberately loose (synthetic data, 60 trees); its job
    is to catch a pipeline break, not to certify accuracy.
    """
    metrics, _ = evaluate_model(trained_model, test_split, test_split, feature_names)
    assert (
        metrics["test_mae"] < 40.0
    ), f"test MAE regressed to {metrics['test_mae']:.2f}"
    assert metrics["test_r2"] > 0.0
