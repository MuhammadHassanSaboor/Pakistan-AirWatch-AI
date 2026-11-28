"""Compare every trained candidate and select the best one that passed the gate.

Reads the per-model metrics files the training stages write
(``reports/train_metrics*.json``), ranks them by the frozen primary
metric (``test_mae``, tie-break ``mae_h24``) and writes
``reports/model_selection.json`` for ``dvc metrics show``.

Selection is a recommendation, not a promotion: moving a model to
Production still goes through ``src.models.registry promote-production``,
which re-checks the gate and requires a human.

    python -m src.models.select_model
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.config import MODEL_CFG, PROJECT_ROOT

log = logging.getLogger(__name__)

REPORTS = PROJECT_ROOT / "reports"
PRIMARY = MODEL_CFG["metrics"]["primary"]
TIEBREAK = MODEL_CFG["metrics"]["tiebreaker"]


def load_candidates(reports_dir: Path = REPORTS) -> list[dict[str, Any]]:
    out = []
    for path in sorted(reports_dir.glob("train_metrics*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Skipping unreadable %s: %s", path.name, exc)
            continue
        if PRIMARY not in data:
            log.warning("Skipping %s: no %s", path.name, PRIMARY)
            continue
        data["source_file"] = path.name
        out.append(data)
    return out


def select(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        candidates,
        key=lambda c: (c[PRIMARY], c.get(TIEBREAK, float("inf"))),
    )
    eligible = [c for c in ranked if c.get("quality_gate_passed")]
    best = eligible[0] if eligible else None

    table = [
        {
            "rank": i,
            "model_family": c.get("model_family"),
            "member": c.get("member"),
            "run_name": c.get("run_name"),
            PRIMARY: c[PRIMARY],
            "test_rmse": c.get("test_rmse"),
            "test_r2": c.get("test_r2"),
            "mae_h1": c.get("mae_h1"),
            "mae_h24": c.get("mae_h24"),
            "improvement_pct": c.get("improvement_pct"),
            "quality_gate_passed": bool(c.get("quality_gate_passed")),
        }
        for i, c in enumerate(ranked, start=1)
    ]

    result: dict[str, Any] = {
        "n_candidates": len(candidates),
        "n_passed_gate": len(eligible),
        "selected_run": best.get("run_name") if best else None,
        "selected_family": best.get("model_family") if best else None,
        "selected_test_mae": best[PRIMARY] if best else None,
        "ranking": table,
    }
    if len(ranked) >= 2 and best is not None:
        runner_up = next((c for c in eligible[1:]), None)
        if runner_up:
            result["margin_over_runner_up_pct"] = round(
                100.0 * (runner_up[PRIMARY] - best[PRIMARY]) / runner_up[PRIMARY], 3
            )
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    candidates = load_candidates()
    if not candidates:
        raise SystemExit("No reports/train_metrics*.json found — train a model first.")

    result = select(candidates)
    out = REPORTS / "model_selection.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"{'rank':>4}  {'family':<14} {'run':<34} {PRIMARY:>9}  gate")
    for row in result["ranking"]:
        print(
            f"{row['rank']:>4}  {row['model_family'] or '-':<14} "
            f"{(row['run_name'] or '-')[:34]:<34} {row[PRIMARY]:>9.4f}  "
            f"{'PASS' if row['quality_gate_passed'] else 'FAIL'}"
        )
    print(f"\nSelected: {result['selected_run']}  ({result['selected_family']})")
    print(f"Written:  {out}")


if __name__ == "__main__":
    main()
