"""Data-drift detection with Evidently.

Prometheus watches the *service*; this watches the *data*. They answer
different questions:

    Prometheus : "is the API healthy?"
    Evidently  : "is the API still being asked about the world it was
                  trained on?"

A model can serve 200s with perfect latency while being completely
wrong, because the input distribution moved underneath it. In this
project that is not hypothetical: Pakistani air quality is strongly
seasonal, so a model trained mostly on summer data will drift every
October when the smog season starts.

Run
---
    python -m src.monitoring.drift
    python -m src.monitoring.drift --simulate     # controlled test
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import DATA_CFG, PROJECT_ROOT, resolve

log = logging.getLogger(__name__)

# Features worth monitoring. Deliberately the physical inputs rather
# than every engineered column: lag features drift mechanically with
# the target and would drown out the real signal.
MONITORED = [
    "pm2_5",
    "pm10",
    "nitrogen_dioxide",
    "ozone",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "boundary_layer_height",
]

# A feature counts as drifted when its PSI exceeds this. The usual rule
# of thumb: <0.1 stable, 0.1-0.25 moderate, >0.25 significant.
PSI_SIGNIFICANT = 0.25

# Retrain when at least this share of monitored features show
# significant PSI drift. With the 8 features above that is 2 or more.
#
# Why PSI and not Evidently's drift_share: drift_share counts columns
# whose statistical test (KS) rejects "same distribution". With tens of
# thousands of rows per window, KS rejects on differences far too small
# to matter, so the share saturates at 100% and fired even on a control
# window of two adjacent weeks (notebook 03, section 3.2). PSI measures
# how MUCH a distribution moved, not whether the move is detectable, so
# it separates the cases: control 1/8, seasonal 2/8, simulated smog 6/8.
DRIFT_THRESHOLD = 0.25


def _load_reference(n_days: int = 90) -> pd.DataFrame:
    """The most recent slice of training data = 'normal'."""
    path = resolve(DATA_CFG["paths"]["raw_combined"])
    if not path.exists():
        raise FileNotFoundError(
            f"Reference dataset missing: {path}. Run the ingestion pipeline."
        )
    df = pd.read_parquet(path)
    cutoff = df["timestamp"].max() - pd.Timedelta(days=n_days)
    return df[df["timestamp"] >= cutoff]


def _load_current() -> pd.DataFrame:
    """The rolling window the hourly DAG maintains."""
    path = PROJECT_ROOT / "data" / "interim" / "live_history.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"No live history at {path}. The hourly ingest DAG populates it."
        )
    return pd.read_parquet(path)


def _psi(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """Population Stability Index.

    A dependency-free fallback so drift detection still works if
    Evidently cannot be imported (its API changes between versions).
    Rule of thumb: <0.1 stable, 0.1-0.25 moderate, >0.25 significant.
    """
    ref = reference.dropna()
    cur = current.dropna()
    if len(ref) < 20 or len(cur) < 20:
        return 0.0

    edges = np.histogram_bin_edges(ref, bins=bins)
    edges[0], edges[-1] = -np.inf, np.inf

    ref_pct = np.histogram(ref, bins=edges)[0] / len(ref)
    cur_pct = np.histogram(cur, bins=edges)[0] / len(cur)

    # Avoid division by zero in empty bins.
    eps = 1e-6
    ref_pct = np.clip(ref_pct, eps, None)
    cur_pct = np.clip(cur_pct, eps, None)

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def _evidently_report(
    reference: pd.DataFrame, current: pd.DataFrame, out_html: Path
) -> dict[str, Any] | None:
    """Try Evidently; return None if the installed API differs."""
    try:
        from evidently.metric_preset import DataDriftPreset
        from evidently.report import Report

        report = Report(metrics=[DataDriftPreset()])
        report.run(reference_data=reference, current_data=current)
        out_html.parent.mkdir(parents=True, exist_ok=True)
        report.save_html(str(out_html))

        payload = report.as_dict()
        result = payload["metrics"][0]["result"]
        return {
            "n_features": int(result["number_of_columns"]),
            "n_drifted": int(result["number_of_drifted_columns"]),
            "drift_share": float(result["share_of_drifted_columns"]),
            "engine": "evidently",
            "html": str(out_html),
        }
    except Exception as exc:
        log.warning("Evidently unavailable (%s); using PSI fallback", exc)
        return None


def run_drift_check(
    reference: pd.DataFrame | None = None,
    current: pd.DataFrame | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Compare current data against the training reference."""
    reference = _load_reference() if reference is None else reference
    current = _load_current() if current is None else current

    cols = [c for c in MONITORED if c in reference.columns and c in current.columns]
    if not cols:
        raise ValueError("No monitored columns present in both datasets")

    out_dir = out_dir or (PROJECT_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "drift_report.html"

    result = _evidently_report(reference[cols], current[cols], html_path)

    # PSI is computed whichever engine ran: it drives the retrain
    # decision, and it is interpretable per feature.
    per_feature = {c: _psi(reference[c], current[c]) for c in cols}
    drifted = [c for c, v in per_feature.items() if v > PSI_SIGNIFICANT]
    psi_drift_share = len(drifted) / len(cols)

    if result is None:
        # No Evidently: its share would have been the PSI share anyway.
        result = {
            "n_features": len(cols),
            "n_drifted": len(drifted),
            "drift_share": psi_drift_share,
            "engine": "psi",
        }

    result.update(
        {
            "psi": {k: round(v, 4) for k, v in per_feature.items()},
            "drifted_features": drifted,
            "psi_drift_share": psi_drift_share,
            "max_psi": round(max(per_feature.values()), 4),
            "generated_at": datetime.now(UTC).isoformat(),
            "reference_rows": int(len(reference)),
            "current_rows": int(len(current)),
            "psi_significant": PSI_SIGNIFICANT,
            "threshold": DRIFT_THRESHOLD,
            # The decision uses PSI, never Evidently's drift_share,
            # which saturates at large sample sizes (see DRIFT_THRESHOLD).
            "retrain_recommended": bool(psi_drift_share >= DRIFT_THRESHOLD),
        }
    )

    json_path = out_dir / "drift_report.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info(
        "Drift: PSI>%.2f in %d/%d features (%.1f%%), retrain=%s",
        PSI_SIGNIFICANT,
        len(drifted),
        len(cols),
        psi_drift_share * 100,
        result["retrain_recommended"],
    )
    return result


def simulate_drift(multiplier: float = 3.5) -> dict[str, Any]:
    """Produce a controlled drift event for the demonstration.

    The course specification explicitly permits a simulated event when
    real drift is unavailable. This shifts the current window towards
    smog-season conditions: pollution up, temperature down, mixing
    height collapsed — physically coherent, not random noise.
    """
    reference = _load_reference()
    current = reference.copy()

    for col in ("pm2_5", "pm10", "nitrogen_dioxide"):
        if col in current.columns:
            current[col] = current[col] * multiplier
    if "temperature_2m" in current.columns:
        current["temperature_2m"] = current["temperature_2m"] - 12
    if "boundary_layer_height" in current.columns:
        current["boundary_layer_height"] = current["boundary_layer_height"] * 0.3
    if "wind_speed_10m" in current.columns:
        current["wind_speed_10m"] = current["wind_speed_10m"] * 0.4

    out_dir = PROJECT_ROOT / "reports" / "drift_simulation"
    result = run_drift_check(reference=reference, current=current, out_dir=out_dir)
    result["simulated"] = True
    result["multiplier"] = multiplier
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a data-drift check")
    ap.add_argument(
        "--simulate",
        action="store_true",
        help="generate a controlled drift event for the demo",
    )
    ap.add_argument("--multiplier", type=float, default=3.5)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    result = simulate_drift(args.multiplier) if args.simulate else run_drift_check()

    print(f"\nEngine          : {result['engine']}")
    print(f"Features checked: {result['n_features']}")
    print(f"Drifted (PSI)   : {len(result['drifted_features'])}")
    print(f"PSI drift share : {result['psi_drift_share']:.1%}")
    print(f"Threshold       : {result['threshold']:.0%}")
    print(f"Evidently share : {result['drift_share']:.1%}  (reported, not used)")
    print(f"Retrain needed  : {result['retrain_recommended']}")
    if result.get("psi"):
        print(f"\nPSI by feature (>{PSI_SIGNIFICANT} = significant):")
        for feature, value in sorted(result["psi"].items(), key=lambda kv: -kv[1]):
            flag = "  <-- drifted" if value > PSI_SIGNIFICANT else ""
            print(f"  {feature:24} {value:7.4f}{flag}")


if __name__ == "__main__":
    main()
