# Running API Locally - Manual Instructions

## Step 1: Install Dependencies

**Option A: Using the setup script (recommended):**
```bash
./scripts/setup_and_test_api.sh
```

**Option B: Manual installation:**
```bash
python -m pip install --upgrade pip
python -m pip install fastapi uvicorn httpx pydantic pydantic-settings
```

Or if using conda:
```bash
conda install -c conda-forge fastapi uvicorn httpx pydantic pydantic-settings
```

**Verify installation:**
```bash
python -c "from api.main import app; print('✓ API imports successfully')"
```

## Step 2: Start the API Server

In one terminal, run:
```bash
cd /Users/jay027/Desktop/github_repo/log-analysis-AI-agent
uvicorn api.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

## Step 3: Test Endpoints

### Test Health Endpoint

In another terminal:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status":"ok"}
```

### Test Create Job

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"question":"Why are timeouts happening?","log_path":"data/sample.log"}'
```

Expected response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "queued_at": "2024-02-05T12:00:00",
  "estimated_start_time": null,
  "links": {
    "self": "/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000",
    "report": "/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/report",
    "artifacts": "/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/artifacts"
  }
}
```

### Test Get Job Status

Replace `{job_id}` with the actual job_id from the previous response:
```bash
curl http://localhost:8000/api/v1/jobs/{job_id}
```

### Test Get Job Report (after job completes)

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}/report
```

## Alternative: Use the Test Scripts

**Start server:**
```bash
./scripts/setup_and_test_api.sh
```

**In another terminal, test endpoints:**
```bash
./scripts/test_endpoints.sh
```

Or use the full automated test:
```bash
./scripts/test_api_local.sh
```

## Troubleshooting

1. **Port 8000 already in use**: Change port with `--port 8001`
2. **Module not found**: Make sure you're in the project root directory
3. **Import errors**: Check that all dependencies are installed: `pip install -r requirements.txt`
4. **File not found**: Ensure `data/sample.log` exists or use a valid log file path

## View API Documentation

Once server is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
