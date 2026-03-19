#!/bin/bash
# Poll job status and display progress information
# Usage: ./scripts/poll_job.sh <JOB_ID> [API_URL]

set -e

JOB_ID="${1}"
API_URL="${2:-http://localhost:8000}"

if [ -z "$JOB_ID" ]; then
    echo "Usage: $0 <JOB_ID> [API_URL]"
    echo "Example: $0 abc123 http://localhost:8000"
    exit 1
fi

echo "Polling job: $JOB_ID"
echo "API URL: $API_URL"
echo "Press Ctrl+C to stop"
echo ""

while true; do
    RESPONSE=$(curl -s "$API_URL/api/v1/jobs/$JOB_ID")
    
    STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null || echo "unknown")
    CURRENT_STEP=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('current_step', 'N/A'))" 2>/dev/null || echo "N/A")
    PROGRESS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('progress_pct', 0))" 2>/dev/null || echo "0")
    ARTIFACTS_COUNT=$(echo "$RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('artifacts', [])))" 2>/dev/null || echo "0")
    STEP_STARTED=$(echo "$RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('step_started_at', 'N/A'))" 2>/dev/null || echo "N/A")
    STEP_TIMEOUT=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('step_timeout_seconds', 'N/A'))" 2>/dev/null || echo "N/A")
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('error', ''))" 2>/dev/null || echo "")
    
    # Clear line and print status
    if [ -n "$STEP_TIMEOUT" ] && [ "$STEP_TIMEOUT" != "None" ] && [ "$STEP_TIMEOUT" != "N/A" ]; then
        printf "\r[%s] Status: %-12s | Step: %-20s | Progress: %3d%% | Artifacts: %2d | Timeout: %ss\n" \
            "$(date +%H:%M:%S)" \
            "$STATUS" \
            "$CURRENT_STEP" \
            "$PROGRESS" \
            "$ARTIFACTS_COUNT" \
            "$STEP_TIMEOUT"
    else
        printf "\r[%s] Status: %-12s | Step: %-20s | Progress: %3d%% | Artifacts: %2d\n" \
            "$(date +%H:%M:%S)" \
            "$STATUS" \
            "$CURRENT_STEP" \
            "$PROGRESS" \
            "$ARTIFACTS_COUNT"
    fi
    
    # Check if job is done
    if [ "$STATUS" = "succeeded" ] || [ "$STATUS" = "failed" ] || [ "$STATUS" = "cancelled" ]; then
        echo ""
        echo ""
        echo "Job completed with status: $STATUS"
        if [ -n "$ERROR" ] && [ "$ERROR" != "null" ] && [ "$ERROR" != "" ]; then
            echo "Error: $ERROR"
        fi
        echo ""
        echo "Final artifacts:"
        curl -s "$API_URL/api/v1/jobs/$JOB_ID/artifacts" | python3 -m json.tool 2>/dev/null || echo "Failed to fetch artifacts"
        break
    fi
    
    sleep 2
done
