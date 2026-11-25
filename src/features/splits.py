"""Chronological train/validation/test splitting.

**This module exists so that all three team members split the data
identically.** If Hassan, Mudassar and Ifraz split differently, their
MLflow metrics are not comparable and the whole model comparison is
worthless. Nobody writes their own split logic.

Why not `train_test_split`?
---------------------------
This is a time series. A random split lets the model see 3pm when
predicting 2pm of the same day, which leaks the answer. Reported
accuracy becomes fantasy. We always cut by date.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.config import split_dates

log = logging.getLogger(__name__)


def chrono_split(
    df: pd.DataFrame,
    train_end: str | None = None,
    val_end: str | None = None,
    timestamp_col: str = "timestamp",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split a frame into (train, val, test) by time.

    Dates default to `configs/model_params.yaml` — the single source
    of truth. Pass explicit dates only in tests.
    """
    if train_end is None or val_end is None:
        cfg_train_end, cfg_val_end = split_dates()
        train_end = train_end or cfg_train_end
        val_end = val_end or cfg_val_end

    ts = pd.to_datetime(df[timestamp_col], utc=True)
    t_end = pd.Timestamp(train_end)
    v_end = pd.Timestamp(val_end)

    if t_end.tzinfo is None:
        t_end = t_end.tz_localize("UTC")
    if v_end.tzinfo is None:
        v_end = v_end.tz_localize("UTC")

    if t_end >= v_end:
        raise ValueError(f"train_end ({t_end}) must be before val_end ({v_end})")

    train = df[ts <= t_end]
    val = df[(ts > t_end) & (ts <= v_end)]
    test = df[ts > v_end]

    log.info(
        "Split -> train=%d (..%s)  val=%d  test=%d (%s..)",
        len(train),
        t_end.date(),
        len(val),
        len(test),
        v_end.date(),
    )

    for name, part in (("train", train), ("val", val), ("test", test)):
        if part.empty:
            raise ValueError(
                f"The '{name}' split is empty. Check the split dates in "
                "configs/model_params.yaml against your data's date range."
            )

    return train, val, test


def describe_splits(
    train: pd.DataFrame,
    val: pd.DataFrame,
    test: pd.DataFrame,
    timestamp_col: str = "timestamp",
) -> dict:
    """Summary logged to MLflow so every run records its split."""

    def _part(name: str, d: pd.DataFrame) -> dict:
        ts = pd.to_datetime(d[timestamp_col], utc=True)
        return {
            f"{name}_rows": int(len(d)),
            f"{name}_start": str(ts.min()),
            f"{name}_end": str(ts.max()),
            f"{name}_cities": int(d["city_id"].nunique()) if "city_id" in d else None,
        }

    out: dict = {}
    for name, part in (("train", train), ("val", val), ("test", test)):
        out.update(_part(name, part))
    return out


def assert_no_overlap(
    train: pd.DataFrame,
    val: pd.DataFrame,
    test: pd.DataFrame,
    timestamp_col: str = "timestamp",
) -> None:
    """Guard used by tests: the three windows must not overlap in time."""
    tr = pd.to_datetime(train[timestamp_col], utc=True)
    va = pd.to_datetime(val[timestamp_col], utc=True)
    te = pd.to_datetime(test[timestamp_col], utc=True)

    if tr.max() >= va.min():
        raise AssertionError(f"train end {tr.max()} overlaps val start {va.min()}")
    if va.max() >= te.min():
        raise AssertionError(f"val end {va.max()} overlaps test start {te.min()}")


__all__ = ["chrono_split", "describe_splits", "assert_no_overlap"]
