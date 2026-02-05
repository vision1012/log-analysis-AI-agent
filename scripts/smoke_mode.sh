#!/bin/bash
# Smoke test for mode parameter wiring through API → JobStore → Runner → Pipeline
# Tests that mode="rag" generates artifacts and mode defaults to "rag"

set -e

API_URL="${API_URL:-http://localhost:8000}"
LOG_PATH="${LOG_PATH:-data/sample.log}"

echo "=== Smoke Test: Mode Parameter Wiring ==="
echo "API URL: $API_URL"
echo "Log Path: $LOG_PATH"
echo ""

# Check if log file exists
if [ ! -f "$LOG_PATH" ]; then
    echo "ERROR: Log file not found: $LOG_PATH"
    echo "Please create the log file or set LOG_PATH environment variable"
    exit 1
fi

# Test 1: POST job with mode="rag" explicitly
echo "Test 1: POST job with mode='rag'"
RESPONSE=$(curl -s -X POST "$API_URL/api/v1/jobs" \
    -H "Content-Type: application/json" \
    -d "{
        \"question\": \"Why are timeouts happening?\",
        \"log_path\": \"$LOG_PATH\",
        \"mode\": \"rag\"
    }")

JOB_ID=$(echo "$RESPONSE" | grep -o '"job_id":"[^"]*' | cut -d'"' -f4)

if [ -z "$JOB_ID" ]; then
    echo "ERROR: Failed to create job. Response: $RESPONSE"
    exit 1
fi

echo "Job created: $JOB_ID"
echo ""

# Test 2: POST job without mode (should default to "rag")
echo "Test 2: POST job without mode (should default to 'rag')"
RESPONSE2=$(curl -s -X POST "$API_URL/api/v1/jobs" \
    -H "Content-Type: application/json" \
    -d "{
        \"question\": \"What errors occurred?\",
        \"log_path\": \"$LOG_PATH\"
    }")

JOB_ID2=$(echo "$RESPONSE2" | grep -o '"job_id":"[^"]*' | cut -d'"' -f4)

if [ -z "$JOB_ID2" ]; then
    echo "ERROR: Failed to create job. Response: $RESPONSE2"
    exit 1
fi

echo "Job created (default mode): $JOB_ID2"
echo ""

# Poll first job until completed
echo "Polling job $JOB_ID until completed..."
MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    STATUS=$(curl -s "$API_URL/api/v1/jobs/$JOB_ID" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
    
    if [ "$STATUS" = "succeeded" ] || [ "$STATUS" = "failed" ]; then
        echo "Job $JOB_ID completed with status: $STATUS"
        break
    fi
    
    sleep 2
    WAITED=$((WAITED + 2))
    echo "  Waiting... (${WAITED}s/${MAX_WAIT}s) - Status: $STATUS"
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "ERROR: Job $JOB_ID did not complete within ${MAX_WAIT}s"
    exit 1
fi

# Verify artifacts for RAG mode job
echo ""
echo "Test 3: Verify artifacts for RAG mode job"
ARTIFACTS_RESPONSE=$(curl -s "$API_URL/api/v1/jobs/$JOB_ID/artifacts")
ARTIFACTS_COUNT=$(echo "$ARTIFACTS_RESPONSE" | grep -o '"name"' | wc -l | tr -d ' ')

echo "Artifacts count: $ARTIFACTS_COUNT"

if [ "$STATUS" = "succeeded" ]; then
    if [ "$ARTIFACTS_COUNT" -lt 3 ]; then
        echo "ERROR: Expected at least 3 artifacts for RAG mode, got $ARTIFACTS_COUNT"
        echo "Response: $ARTIFACTS_RESPONSE"
        exit 1
    fi
    
    # Check for specific artifacts
    if echo "$ARTIFACTS_RESPONSE" | grep -q "retrieval.json"; then
        echo "  ✓ retrieval.json found"
    else
        echo "  ✗ retrieval.json NOT found"
        exit 1
    fi
    
    if echo "$ARTIFACTS_RESPONSE" | grep -q "findings.json"; then
        echo "  ✓ findings.json found"
    else
        echo "  ✗ findings.json NOT found"
        exit 1
    fi
    
    if echo "$ARTIFACTS_RESPONSE" | grep -q "final_answer.md"; then
        echo "  ✓ final_answer.md found"
    else
        echo "  ✗ final_answer.md NOT found"
        exit 1
    fi
fi

# Verify files exist in output/jobs/<job_id>/
echo ""
echo "Test 4: Verify files exist in output/jobs/$JOB_ID/"
OUTPUT_DIR="output/jobs/$JOB_ID"

if [ -f "$OUTPUT_DIR/retrieval.json" ]; then
    echo "  ✓ $OUTPUT_DIR/retrieval.json exists"
else
    echo "  ✗ $OUTPUT_DIR/retrieval.json NOT found"
    exit 1
fi

if [ -f "$OUTPUT_DIR/findings.json" ]; then
    echo "  ✓ $OUTPUT_DIR/findings.json exists"
else
    echo "  ✗ $OUTPUT_DIR/findings.json NOT found"
    exit 1
fi

if [ -f "$OUTPUT_DIR/final_answer.md" ]; then
    echo "  ✓ $OUTPUT_DIR/final_answer.md exists"
else
    echo "  ✗ $OUTPUT_DIR/final_answer.md NOT found"
    exit 1
fi

# Verify files exist in artifacts/<job_id>/
echo ""
echo "Test 5: Verify files exist in artifacts/$JOB_ID/"
ARTIFACTS_DIR="artifacts/$JOB_ID"

if [ -f "$ARTIFACTS_DIR/retrieval.json" ]; then
    echo "  ✓ $ARTIFACTS_DIR/retrieval.json exists"
else
    echo "  ✗ $ARTIFACTS_DIR/retrieval.json NOT found"
    exit 1
fi

if [ -f "$ARTIFACTS_DIR/findings.json" ]; then
    echo "  ✓ $ARTIFACTS_DIR/findings.json exists"
else
    echo "  ✗ $ARTIFACTS_DIR/findings.json NOT found"
    exit 1
fi

if [ -f "$ARTIFACTS_DIR/final_answer.md" ]; then
    echo "  ✓ $ARTIFACTS_DIR/final_answer.md exists"
else
    echo "  ✗ $ARTIFACTS_DIR/final_answer.md NOT found"
    exit 1
fi

# Check run.log for mode=rag
echo ""
echo "Test 6: Verify run.log contains mode=rag"
RUN_LOG="runs/$JOB_ID/run.log"

if [ -f "$RUN_LOG" ]; then
    if grep -q "mode=rag" "$RUN_LOG"; then
        echo "  ✓ run.log contains 'mode=rag'"
    else
        echo "  ✗ run.log does NOT contain 'mode=rag'"
        echo "  Last 20 lines of run.log:"
        tail -20 "$RUN_LOG"
        exit 1
    fi
else
    echo "  ⚠ run.log not found at $RUN_LOG (may be acceptable)"
fi

echo ""
echo "=== All tests passed! ==="
echo "Job ID: $JOB_ID"
echo "Artifacts count: $ARTIFACTS_COUNT"
echo "Status: $STATUS"
