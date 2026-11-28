"""Champion / challenger promotion for the locally served model — owned by MUDASSAR.

The API serves whatever is in ``models/production/`` (model.pkl +
metadata.json). This module decides whether a newly trained candidate
replaces it, and keeps every replaced model so it can be rolled back.

Decision rule (the same thresholds as the quality gate):
  1. the candidate passed the quality gate when it was trained, AND
  2. on the SAME, current test split, the candidate's MAE beats the
     champion's by at least ``min_improvement_over_production_pct``.

Rule 2 matters for daily retraining: the test window grows every day,
so comparing today's candidate score with the champion's score from
last week would compare different data. Both are re-scored here.

    python -m src.models.champion status
    python -m src.models.champion promote models/candidates/<run>     # gated
    python -m src.models.champion rollback
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.config import MODEL_CFG, PROJECT_ROOT, quality_gate

log = logging.getLogger(__name__)

PRODUCTION = PROJECT_ROOT / "models" / "production"
ARCHIVE = PROJECT_ROOT / "models" / "archive"


def _meta(model_dir: Path) -> dict[str, Any]:
    path = Path(model_dir) / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _mae(model, frame: pd.DataFrame, features: list[str]) -> float:
    X = frame.reindex(columns=features)
    pred = np.clip(model.predict(X), 0, None)
    return float(np.mean(np.abs(frame["y"].to_numpy() - pred)))


def compare(candidate_dir: Path, test_df: pd.DataFrame) -> dict[str, Any]:
    """Score candidate and champion on the same test frame and decide."""
    candidate_dir = Path(candidate_dir)
    cand_meta = _meta(candidate_dir)
    cand_model = joblib.load(candidate_dir / "model.pkl")
    cand_mae = _mae(cand_model, test_df, cand_meta["feature_names"])

    min_gain = float(quality_gate()["min_improvement_over_production_pct"])
    result: dict[str, Any] = {
        "candidate": cand_meta.get("run_name", candidate_dir.name),
        "candidate_mae": round(cand_mae, 4),
        "candidate_gate_passed": bool(cand_meta.get("quality_gate_passed")),
        "min_improvement_pct": min_gain,
        "test_rows": len(test_df),
    }

    if not (PRODUCTION / "model.pkl").exists():
        result.update(champion=None, champion_mae=None, improvement_pct=None)
        result["promote"] = result["candidate_gate_passed"]
        result["reason"] = (
            "no champion yet; candidate passed the gate"
            if result["promote"]
            else "candidate failed the quality gate"
        )
        return result

    champ_meta = _meta(PRODUCTION)
    champ_model = joblib.load(PRODUCTION / "model.pkl")
    champ_mae = _mae(champ_model, test_df, champ_meta.get("feature_names", []))
    gain = 100.0 * (champ_mae - cand_mae) / champ_mae if champ_mae > 0 else 0.0

    result.update(
        champion=champ_meta.get("run_name", "unknown"),
        champion_mae=round(champ_mae, 4),
        improvement_pct=round(gain, 3),
    )
    if not result["candidate_gate_passed"]:
        result["promote"], result["reason"] = False, "candidate failed the quality gate"
    elif gain < min_gain:
        result["promote"] = False
        result["reason"] = f"only {gain:.2f}% better than champion (need {min_gain}%)"
    else:
        result["promote"], result["reason"] = True, f"{gain:.2f}% better than champion"
    return result


def promote(candidate_dir: Path, decision: dict[str, Any] | None = None) -> Path:
    """Archive the current champion, then install the candidate."""
    candidate_dir = Path(candidate_dir)
    meta = _meta(candidate_dir)
    if not meta.get("quality_gate_passed"):
        raise RuntimeError(
            f"{candidate_dir.name} failed the quality gate; refusing to promote"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    previous = None
    if (PRODUCTION / "model.pkl").exists():
        previous = _meta(PRODUCTION).get("run_name", "unknown")
        dest = ARCHIVE / f"{stamp}__{previous}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(PRODUCTION, dest)
        log.info("Archived champion %s -> %s", previous, dest)

    PRODUCTION.mkdir(parents=True, exist_ok=True)
    for item in PRODUCTION.iterdir():
        if item.is_file():
            item.unlink()
    shutil.copy2(candidate_dir / "model.pkl", PRODUCTION / "model.pkl")

    meta.update(
        stage="Production",
        version=meta.get("run_name"),
        promoted_at=datetime.now(UTC).isoformat(),
        exported_at=datetime.now(UTC).isoformat(),
        previous_champion=previous,
        promotion_decision=decision,
    )
    (PRODUCTION / "metadata.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8"
    )
    log.info("Promoted %s to production", meta.get("run_name"))
    return PRODUCTION


def rollback() -> str:
    """Restore the most recently archived champion."""
    archived = sorted(ARCHIVE.glob("*/model.pkl")) if ARCHIVE.exists() else []
    if not archived:
        raise RuntimeError("No archived model to roll back to")
    source = archived[-1].parent
    for item in PRODUCTION.iterdir():
        if item.is_file():
            item.unlink()
    for item in source.iterdir():
        if item.is_file():
            shutil.copy2(item, PRODUCTION / item.name)
    shutil.rmtree(source)
    name = _meta(PRODUCTION).get("run_name", source.name)
    log.info("Rolled back to %s", name)
    return name


def status() -> dict[str, Any]:
    meta = _meta(PRODUCTION)
    return {
        "champion": meta.get("run_name"),
        "model_family": meta.get("model_family"),
        "test_mae": (meta.get("metrics") or {}).get("test_mae"),
        "promoted_at": meta.get("promoted_at"),
        "archived_versions": len(list(ARCHIVE.glob("*/model.pkl")))
        if ARCHIVE.exists()
        else 0,
        "target": MODEL_CFG["target"],
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    ap = argparse.ArgumentParser(description="Local champion/challenger operations")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("promote", help="promote a gated candidate (no comparison)")
    p.add_argument("candidate_dir")
    sub.add_parser("rollback")
    args = ap.parse_args()

    if args.cmd == "status":
        print(json.dumps(status(), indent=2, default=str))
    elif args.cmd == "promote":
        print(f"Production -> {promote(Path(args.candidate_dir))}")
    else:
        print(f"Rolled back to {rollback()}")


if __name__ == "__main__":
    main()
