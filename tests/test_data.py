"""Data tests: schema validation and quality rules."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.cities import build_city_table, slugify
from src.data.validation import check_quality, validate_raw, validate_schema


# ── schema ────────────────────────────────────────────────────
def test_valid_data_passes_schema(sample_raw):
    ok, report = validate_schema(sample_raw)
    assert ok, report


def test_negative_pm25_rejected(sample_raw):
    bad = sample_raw.copy()
    bad.loc[0, "pm2_5"] = -5.0
    ok, report = validate_schema(bad)
    assert not ok
    assert report["n_failure_cases"] >= 1


def test_impossible_pm25_rejected(sample_raw):
    """3000 µg/m³ indicates a unit error, not real smog."""
    bad = sample_raw.copy()
    bad.loc[0, "pm2_5"] = 3000.0
    ok, _ = validate_schema(bad)
    assert not ok


def test_coordinates_outside_pakistan_rejected(sample_raw):
    bad = sample_raw.copy()
    bad["latitude"] = 51.5  # London
    bad["longitude"] = -0.12
    ok, _ = validate_schema(bad)
    assert not ok


def test_humidity_above_100_rejected(sample_raw):
    bad = sample_raw.copy()
    bad.loc[0, "relative_humidity_2m"] = 150.0
    ok, _ = validate_schema(bad)
    assert not ok


def test_missing_timestamp_rejected(sample_raw):
    bad = sample_raw.copy()
    bad.loc[0, "timestamp"] = pd.NaT
    ok, _ = validate_schema(bad)
    assert not ok


def test_nulls_in_pollutants_are_allowed(sample_raw):
    """Gaps are normal in real feeds; they must not fail the schema."""
    tolerant = sample_raw.copy()
    tolerant.loc[0:10, "pm2_5"] = None
    ok, report = validate_schema(tolerant)
    assert ok, report


# ── quality rules ─────────────────────────────────────────────
def test_duplicates_detected(sample_raw):
    dup = pd.concat([sample_raw, sample_raw.head(5)], ignore_index=True)
    report = check_quality(dup)
    check = next(
        c for c in report["checks"] if c["check"] == "no_duplicate_city_timestamp"
    )
    assert not check["passed"]
    assert check["detail"]["duplicates"] == 5


def test_excessive_missing_target_detected(sample_raw):
    bad = sample_raw.copy()
    n = int(len(bad) * 0.5)
    bad.loc[: n - 1, "pm2_5"] = None
    report = check_quality(bad)
    check = next(c for c in report["checks"] if c["check"] == "target_completeness")
    assert not check["passed"]


def test_pm25_above_pm10_detected(sample_raw):
    bad = sample_raw.copy()
    bad["pm10"] = bad["pm2_5"] * 0.5  # physically impossible
    report = check_quality(bad)
    check = next(c for c in report["checks"] if c["check"] == "pm25_not_above_pm10")
    assert not check["passed"]


def test_flatline_detected(sample_raw):
    bad = sample_raw.copy()
    mask = bad.city_id == "lahore"
    idx = bad[mask].index[:40]
    bad.loc[idx, "pm2_5"] = 77.0  # a stuck sensor
    report = check_quality(bad)
    check = next(c for c in report["checks"] if c["check"] == "no_long_flatlines")
    assert not check["passed"]


def test_stale_data_detected(sample_raw):
    """Synthetic data is from 2024, so the freshness check must fail."""
    report = check_quality(sample_raw)
    check = next(c for c in report["checks"] if c["check"] == "data_freshness")
    assert not check["passed"]


def test_validate_raw_returns_report_without_raising(sample_raw):
    """Airflow needs a report, not an exception."""
    ok, report = validate_raw(sample_raw)
    assert isinstance(ok, bool)
    assert "overall_status" in report
    assert "schema" in report
    assert "quality" in report


def test_validate_raw_on_broken_data_does_not_raise():
    broken = pd.DataFrame({"city_id": ["x"], "timestamp": [pd.NaT]})
    ok, report = validate_raw(broken)
    assert not ok
    assert report["overall_status"] == "fail"


# ── city reference table ──────────────────────────────────────
def test_city_table_has_over_100_cities():
    df = build_city_table()
    assert len(df) >= 100, f"only {len(df)} cities; requirement is 100+"


def test_city_ids_are_unique():
    df = build_city_table()
    assert df.city_id.is_unique


def test_all_provinces_represented():
    df = build_city_table()
    expected = {
        "Punjab",
        "Sindh",
        "Khyber Pakhtunkhwa",
        "Balochistan",
        "Gilgit-Baltistan",
        "Azad Jammu & Kashmir",
        "Islamabad",
    }
    assert expected <= set(df.province)


def test_all_cities_inside_pakistan():
    df = build_city_table()
    assert df.latitude.between(23.5, 37.1).all()
    assert df.longitude.between(60.8, 77.9).all()


def test_slugify_produces_stable_keys():
    assert slugify("Dera Ghazi Khan") == "dera_ghazi_khan"
    assert slugify("Azad Jammu & Kashmir") == "azad_jammu_kashmir"
    assert slugify("  Mirpur  ") == "mirpur"


@pytest.mark.parametrize(
    "city", ["lahore", "karachi", "islamabad", "gwadar", "skardu", "quetta", "peshawar"]
)
def test_key_cities_present(city):
    df = build_city_table()
    assert city in set(df.city_id), f"{city} missing from the reference table"
