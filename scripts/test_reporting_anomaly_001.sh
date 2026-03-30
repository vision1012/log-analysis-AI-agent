#!/usr/bin/env bash
# Run the full debug-agent pipeline (includes reporting / final summaries) for anomaly_001.
# Optional: OLLAMA_HOST + OLLAMA_MODEL for polished reporting; otherwise deterministic text is used.
#
#   export API_BASE=http://localhost:8000
#   ./scripts/test_reporting_anomaly_001.sh

set -euo pipefail
BASE="${API_BASE:-http://localhost:8000}"
echo "POST ${BASE}/debug-agent/run body={\"anomaly_id\":\"anomaly_001\"}"
curl -sS -X POST "${BASE}/debug-agent/run" \
  -H "Content-Type: application/json" \
  -d '{"anomaly_id":"anomaly_001"}' | python3 -m json.tool
