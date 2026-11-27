---
name: ml-pipeline
description: Run, reproduce or debug the AirWatch ML pipeline — DVC stages, training, the quality gate, MLflow registry promotion and rollback. Use for "dvc repro", "train the model", "promote", "rollback", "demo the quality gate", or data-version recovery.
---

# ML pipeline operations

## End-to-end (manual order, what `dvc repro` automates)
```bash
python -m src.data.cities
python -m src.data.ingestion --limit 12      # small sample; full backfill takes hours
python -m src.data.validation --strict
python -m src.features.build_features
python -m src.models.train_baselines --model persistence   # baseline first, always
python -m src.models.train_xgboost
```

## DVC
```bash
dvc repro            # run changed stages
dvc dag              # show graph
dvc metrics show / dvc metrics diff <rev>
dvc push / dvc pull  # remote = DagsHub (credentials in .dvc/config.local, never committed)
```
Reproducibility demo: `git checkout <old-commit> && dvc checkout` → old code + old data.
`.dvc` merge conflict: keep one side's `md5`/`outs`, then `dvc checkout` and re-`dvc add` if the data itself was merged.

## Quality gate (`configs/model_params.yaml → quality_gate`)
- test MAE ≤ `max_test_mae`
- ≥ `min_improvement_over_baseline_pct` better than persistence
- ≥ `min_improvement_over_production_pct` better than current Production
Demo a failure: `bash scripts/demo_quality_gate.sh`.

## Registry
```bash
python -m src.models.registry compare            # member comparison table
python -m src.models.registry promote <run_id>   # → Staging
python -m src.models.registry promote-production <version>  # re-runs the gate
python -m src.models.registry rollback           # previous Production
python -m src.models.registry export-production  # copy for the API
```
`promote_to_production()` is the only path to Production — never bypass it.

## MLflow
Set `MLFLOW_TRACKING_URI` (+ `MLFLOW_TRACKING_USERNAME/PASSWORD` for DagsHub) in `.env`.
Every run must log: algorithm, params, git commit, DVC data hash, metrics, duration, artifacts —
use helpers in `src/models/tracking.py`, not raw `mlflow.log_*`.
