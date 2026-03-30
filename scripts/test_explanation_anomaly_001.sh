#!/usr/bin/env bash
# Call the explanation endpoint for seeded anomaly_001 (requires API + Neo4j + RCA data).
# Optional: OLLAMA_HOST + OLLAMA_MODEL for live Ollama; without them the API uses stub/safe fallback.
#
#   export API_BASE=http://localhost:8000
#   ./scripts/test_explanation_anomaly_001.sh

set -euo pipefail
BASE="${API_BASE:-http://localhost:8000}"
echo "GET ${BASE}/api/v1/rca/explanation/anomaly_001"
curl -sS "${BASE}/api/v1/rca/explanation/anomaly_001" | python3 -m json.tool
