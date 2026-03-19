# FastAPI API Tests

Minimal pytest tests for FastAPI endpoints using TestClient and mocks.

## Prerequisites

Install pytest and httpx (required by TestClient):

```bash
pip install pytest httpx
```

Or add to `requirements.txt`:
```
pytest>=7.4.0
httpx>=0.24.0
```

## Running Tests

Run all API tests:
```bash
pytest code_testing/test_api.py -v
```

Run specific test class:
```bash
pytest code_testing/test_api.py::TestHealthEndpoint -v
pytest code_testing/test_api.py::TestCreateJob -v
pytest code_testing/test_api.py::TestGetJob -v
```

Run with coverage:
```bash
pytest code_testing/test_api.py --cov=api --cov-report=html
```

## Test Structure

### TestHealthEndpoint
- `test_health_check`: Verifies `/health` returns `{"status": "ok"}`

### TestCreateJob
- `test_create_job_returns_job_id`: Verifies POST `/api/v1/jobs` returns job_id immediately
- `test_create_job_without_log_path`: Verifies validation error when log_path missing
- `test_create_job_invalid_log_path`: Verifies error when log file doesn't exist

### TestGetJob
- `test_get_job_queued`: Verifies GET returns queued job
- `test_get_job_running`: Verifies GET returns running job
- `test_get_job_succeeded`: Verifies GET returns succeeded job
- `test_get_job_not_found`: Verifies 404 for nonexistent job

### TestJobStatusFlow
- `test_job_status_flow`: Verifies complete flow: queued -> running -> succeeded

## Mocking Strategy

Tests use `unittest.mock` to mock:
- `job_store`: Avoids actual database/file operations
- `job_runner`: Avoids running heavy pipeline

This makes tests fast and isolated.

## Example Output

```
code_testing/test_api.py::TestHealthEndpoint::test_health_check PASSED
code_testing/test_api.py::TestCreateJob::test_create_job_returns_job_id PASSED
code_testing/test_api.py::TestCreateJob::test_create_job_without_log_path PASSED
code_testing/test_api.py::TestCreateJob::test_create_job_invalid_log_path PASSED
code_testing/test_api.py::TestGetJob::test_get_job_queued PASSED
code_testing/test_api.py::TestGetJob::test_get_job_running PASSED
code_testing/test_api.py::TestGetJob::test_get_job_succeeded PASSED
code_testing/test_api.py::TestGetJob::test_get_job_not_found PASSED
code_testing/test_api.py::TestJobStatusFlow::test_job_status_flow PASSED
```

## Notes

- Tests use `TestClient` from FastAPI for fast in-memory testing
- Background tasks are mocked, so they don't actually execute
- JobStore is mocked to return predictable test data
- No actual pipeline execution occurs during tests
