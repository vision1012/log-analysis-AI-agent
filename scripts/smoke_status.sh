#!/bin/bash
# Smoke test to verify job status is set correctly after pipeline success
# Usage: ./scripts/smoke_status.sh [API_URL]

set -e

API_URL="${1:-http://localhost:8000}"

echo "=== Smoke Test: Job Status After Success ==="
echo "API URL: $API_URL"
echo ""

# Create a RAG job
echo "1. Creating RAG job..."
RESPONSE=$(curl -s -X POST "$API_URL/api/v1/jobs" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why are timeouts happening?",
    "log_path": "data/sample.log",
    "mode": "rag"
  }')

JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('job_id', ''))" 2>/dev/null || echo "")

if [ -z "$JOB_ID" ]; then
    echo "ERROR: Failed to create job. Response: $RESPONSE"
    exit 1
fi

echo "Job created: $JOB_ID"
echo ""

# Poll until terminal state
echo "2. Polling job status..."
MAX_ITERATIONS=60
ITERATION=0

while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    RESPONSE=$(curl -s "$API_URL/api/v1/jobs/$JOB_ID")
    STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null || echo "unknown")
    PROGRESS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('progress_pct', 0))" 2>/dev/null || echo "0")
    CURRENT_STEP=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('current_step', 'N/A'))" 2>/dev/null || echo "N/A")
    
    printf "\r[%d/%d] Status: %-12s | Progress: %3d%% | Step: %-20s" \
        $((ITERATION + 1)) $MAX_ITERATIONS "$STATUS" "$PROGRESS" "$CURRENT_STEP"
    
    if [ "$STATUS" = "succeeded" ] || [ "$STATUS" = "failed" ] || [ "$STATUS" = "cancelled" ]; then
        echo ""
        echo ""
        break
    fi
    
    sleep 2
    ITERATION=$((ITERATION + 1))
done

if [ $ITERATION -eq $MAX_ITERATIONS ]; then
    echo ""
    echo "ERROR: Job did not reach terminal state within timeout"
    exit 1
fi

echo "3. Verifying final status..."
FINAL_STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))" 2>/dev/null || echo "")
ARTIFACTS_COUNT=$(echo "$RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('artifacts', [])))" 2>/dev/null || echo "0")
ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('error', ''))" 2>/dev/null || echo "")

echo "Final status: $FINAL_STATUS"
echo "Artifacts count: $ARTIFACTS_COUNT"
if [ -n "$ERROR" ] && [ "$ERROR" != "null" ] && [ "$ERROR" != "" ]; then
    echo "Error: $ERROR"
fi
echo ""

# Assertions
echo "4. Running assertions..."

if [ "$FINAL_STATUS" != "succeeded" ]; then
    echo "❌ FAIL: Expected status 'succeeded', got '$FINAL_STATUS'"
    if [ -n "$ERROR" ] && [ "$ERROR" != "null" ] && [ "$ERROR" != "" ]; then
        echo "   Error message: $ERROR"
    fi
    exit 1
fi

if [ "$ARTIFACTS_COUNT" -lt 3 ]; then
    echo "❌ FAIL: Expected at least 3 artifacts, got $ARTIFACTS_COUNT"
    echo "   Artifacts:"
    echo "$RESPONSE" | python3 -c "import sys, json; [print(f\"     - {a.get('name', 'unknown')}\") for a in json.load(sys.stdin).get('artifacts', [])]" 2>/dev/null || echo "     (failed to parse)"
    exit 1
fi

# Verify specific artifacts exist
ARTIFACTS_JSON=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.dumps([a.get('name', '') for a in json.load(sys.stdin).get('artifacts', [])]))" 2>/dev/null || echo "[]")

HAS_RETRIEVAL=$(echo "$ARTIFACTS_JSON" | python3 -c "import sys, json; print('retrieval.json' in json.load(sys.stdin))" 2>/dev/null || echo "False")
HAS_FINDINGS=$(echo "$ARTIFACTS_JSON" | python3 -c "import sys, json; print('findings.json' in json.load(sys.stdin))" 2>/dev/null || echo "False")
HAS_REPORT=$(echo "$ARTIFACTS_JSON" | python3 -c "import sys, json; print('final_answer.md' in json.load(sys.stdin))" 2>/dev/null || echo "False")

if [ "$HAS_RETRIEVAL" != "True" ]; then
    echo "❌ FAIL: Missing artifact 'retrieval.json'"
    exit 1
fi

if [ "$HAS_FINDINGS" != "True" ]; then
    echo "❌ FAIL: Missing artifact 'findings.json'"
    exit 1
fi

if [ "$HAS_REPORT" != "True" ]; then
    echo "❌ FAIL: Missing artifact 'final_answer.md'"
    exit 1
fi

echo "✅ PASS: Status is 'succeeded'"
echo "✅ PASS: Artifacts count >= 3 ($ARTIFACTS_COUNT)"
echo "✅ PASS: All required artifacts present (retrieval.json, findings.json, final_answer.md)"
echo ""
echo "=== Smoke Test Passed ==="
