#!/usr/bin/env bash
# Deliberately trip a Prometheus alert, for the monitoring demo.
#
#   ./scripts/trigger_alert.sh errors   -> HighAPIErrorRate
#   ./scripts/trigger_alert.sh down     -> APIDown
#
# Then open http://localhost:9090/alerts and screenshot the FIRING state.

set -euo pipefail
MODE="${1:-errors}"
API="${2:-http://localhost:5000}"

case "$MODE" in
  errors)
    echo "Sending 300 malformed requests to raise the error rate..."
    for i in $(seq 1 300); do
      curl -s -o /dev/null -X POST "$API/predict" \
        -H "Content-Type: application/json" \
        -d '{"cities":[{"city_id":"%%%INVALID%%%","horizon":-1}]}' || true
    done
    echo "Done. HighAPIErrorRate evaluates over 5m and fires after 2m."
    ;;
  down)
    echo "Stopping the API container..."
    docker compose stop api
    echo "APIDown fires after 1 minute. Restore with: docker compose start api"
    ;;
  *)
    echo "Usage: $0 {errors|down} [api_url]" >&2
    exit 1
    ;;
esac

echo
echo "Watch: http://localhost:9090/alerts"
echo "Grafana: http://localhost:3001"
