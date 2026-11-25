#!/usr/bin/env bash
# Prove the quality gate REJECTS a bad model.
#
# This is a required deliverable: an automated pipeline must not
# promote every model it trains. Training with a single tree produces a
# model that cannot beat the persistence baseline, and the gate must
# refuse it.

set -euo pipefail

echo "=============================================================="
echo " Training a deliberately under-powered model (1 tree, depth 1)"
echo "=============================================================="
python -m src.models.train_xgboost --n-estimators 1 --max-depth 1 --lr 0.01 \
  || true

echo
echo "=============================================================="
echo " Expected: 'Quality gate FAILED' above, and NO new registered"
echo " version. The model was trained but is not a deployment"
echo " candidate."
echo "=============================================================="
python -m src.models.registry list
