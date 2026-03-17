#!/bin/bash
# Test API endpoints (run this in a separate terminal while server is running)

set -e

API_URL="http://localhost:8000"

echo "=== Testing Health Endpoint ==="
curl -s "$API_URL/health" | python -m json.tool
echo ""

echo "=== Testing Create Job ==="
JOB_RESPONSE=$(curl -s -X POST "$API_URL/api/v1/jobs" \
  -H "Content-Type: application/json" \
  -d '{"question":"Why are timeouts happening?","log_path":"data/sample.log"}')

echo "$JOB_RESPONSE" | python -m json.tool

# Extract job_id
JOB_ID=$(echo "$JOB_RESPONSE" | python -c "import sys, json; data=json.load(sys.stdin); print(data.get('job_id', ''))" 2>/dev/null || echo "")

if [ -n "$JOB_ID" ]; then
    echo ""
    echo "=== Testing Get Job Status ==="
    echo "Job ID: $JOB_ID"
    sleep 2
    curl -s "$API_URL/api/v1/jobs/$JOB_ID" | python -m json.tool
else
    echo "ERROR: Could not extract job_id from response"
fi

echo ""
echo "=== Testing Complete ==="
