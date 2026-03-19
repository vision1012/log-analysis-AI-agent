#!/bin/bash
# Test script for local API testing

set -e

echo "=== Installing dependencies ==="
pip install fastapi uvicorn httpx

echo ""
echo "=== Checking if port 8000 is available ==="
if lsof -ti:8000 > /dev/null 2>&1; then
    echo "Port 8000 is already in use. Killing existing process..."
    kill $(lsof -ti:8000) 2>/dev/null || true
    sleep 2
fi

echo ""
echo "=== Starting API server in background ==="
uvicorn api.main:app --reload --port 8000 &
SERVER_PID=$!

# Wait for server to start
echo "Waiting for server to start..."
sleep 5

# Check if server is running
if ! curl -s http://localhost:8000/health > /dev/null; then
    echo "ERROR: Server failed to start"
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi

echo ""
echo "=== Testing /health endpoint ==="
curl -s http://localhost:8000/health | python -m json.tool
echo ""

echo ""
echo "=== Testing POST /api/v1/jobs ==="
JOB_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"question":"Why are timeouts happening?","log_path":"data/sample.log"}')

echo "$JOB_RESPONSE" | python -m json.tool

# Extract job_id if available
JOB_ID=$(echo "$JOB_RESPONSE" | python -c "import sys, json; data=json.load(sys.stdin); print(data.get('job_id', ''))" 2>/dev/null || echo "")

if [ -n "$JOB_ID" ]; then
    echo ""
    echo "=== Testing GET /api/v1/jobs/$JOB_ID ==="
    sleep 2  # Give job a moment to start
    curl -s http://localhost:8000/api/v1/jobs/$JOB_ID | python -m json.tool
fi

echo ""
echo "=== Stopping server ==="
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo ""
echo "=== Tests complete ==="
