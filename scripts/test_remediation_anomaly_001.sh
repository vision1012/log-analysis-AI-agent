#!/usr/bin/env bash
# Run the debug-agent pipeline (includes remediation) for anomaly_001.
# Requires API, Neo4j, seeded anomaly, and optional Ollama (OLLAMA_HOST + OLLAMA_MODEL).
#
#   export API_BASE=http://localhost:8000
#   ./scripts/test_remediation_anomaly_001.sh

set -euo pipefail
BASE="${API_BASE:-http://localhost:8000}"
echo "POST ${BASE}/debug-agent/run body={\"anomaly_id\":\"anomaly_001\"}"
curl -sS -X POST "${BASE}/debug-agent/run" \
  -H "Content-Type: application/json" \
  -d '{"anomaly_id":"anomaly_001"}' | python3 -m json.tool
