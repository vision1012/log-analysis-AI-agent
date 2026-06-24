#!/usr/bin/env bash
# Verify critical API routes respond with something other than 404.
# Auth-protected routes may return 401/405/422 — that still means the route exists.
set -euo pipefail
BASE="${API_BASE:-http://127.0.0.1:8000}"

check() {
  local method="$1"
  local path="$2"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "${BASE}${path}" 2>/dev/null || echo "000")
  if [[ "$code" == "404" || "$code" == "000" ]]; then
    echo "FAIL $method $path -> $code"
    return 1
  fi
  echo "PASS $method $path -> $code"
}

echo "API route smoke: $BASE"
check GET /health
check GET /openapi.json
check GET /api/v1/mcp/status
check GET /api/v1/integrations/connections
check POST /api/v1/auth/login
echo "OK"
