#!/usr/bin/env bash
# Roll the deployed model back to the previous version.
#
# Demonstrates the governance requirement that a bad promotion can be
# undone quickly. Takes about 30 seconds end to end.
#
#   ./scripts/rollback.sh [api_url]

set -euo pipefail
API="${1:-http://localhost:5000}"

echo "=== BEFORE ==="
curl -sf "$API/model-info" | python -c "import sys,json;d=json.load(sys.stdin);print(f\"  version : {d['model_version']}\n  stage   : {d['stage']}\n  mae     : {d['metrics'].get('test_mae','n/a')}\")"

echo
echo "=== ROLLING BACK ==="
python -m src.models.registry rollback
python -m src.models.registry export-production

echo
echo "=== RESTARTING SERVICE ==="
if kubectl get deployment airwatch-api -n airwatch >/dev/null 2>&1; then
  kubectl rollout restart deployment/airwatch-api -n airwatch
  kubectl rollout status deployment/airwatch-api -n airwatch --timeout=120s
elif docker compose ps api >/dev/null 2>&1; then
  docker compose up -d --force-recreate api
  sleep 15
else
  echo "  No orchestrator detected. Restart the API process manually."
fi

echo
echo "=== AFTER ==="
curl -sf "$API/model-info" | python -c "import sys,json;d=json.load(sys.stdin);print(f\"  version : {d['model_version']}\n  stage   : {d['stage']}\")"
