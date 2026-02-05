#!/bin/bash
# Setup and test API script

set -e

echo "=== Checking Python version ==="
python --version
which python

echo ""
echo "=== Installing dependencies ==="
python -m pip install --upgrade pip
python -m pip install fastapi uvicorn httpx pydantic pydantic-settings

echo ""
echo "=== Verifying imports ==="
python -c "from api.main import app; print('✓ API imports successfully')" || {
    echo "ERROR: Failed to import API. Check dependencies."
    exit 1
}

echo ""
echo "=== Checking if port 8000 is available ==="
if lsof -ti:8000 > /dev/null 2>&1; then
    echo "Port 8000 is already in use. Killing existing process..."
    kill $(lsof -ti:8000) 2>/dev/null || true
    sleep 2
fi

echo ""
echo "=== Starting API server ==="
echo "Server will start on http://localhost:8000"
echo "Press CTRL+C to stop"
echo ""
uvicorn api.main:app --reload --port 8000 --host 0.0.0.0
