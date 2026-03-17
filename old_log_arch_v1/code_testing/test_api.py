"""
Pytest tests for FastAPI API endpoints.

Uses TestClient and mocks to avoid running heavy pipeline.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.schemas.job import JobRecord


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_job_store():
    """Create mock JobStore."""
    store = MagicMock()
    return store


@pytest.fixture
def mock_job_runner():
    """Create mock JobRunner."""
    runner = MagicMock()
    return runner


@pytest.fixture
def sample_job_id():
    """Generate a sample job ID."""
    return str(uuid4())


@pytest.fixture
def sample_job_record_queued(sample_job_id):
    """Create sample job record with queued status."""
    return JobRecord(
        job_id=sample_job_id,
        status="queued",
        created_at=datetime.now(),
        started_at=None,
        finished_at=None,
        question="Test question",
        input_log_path="data/sample.log",
        model="llama3",
        error=None,
        artifacts=[],
    )


@pytest.fixture
def sample_job_record_running(sample_job_id):
    """Create sample job record with running status."""
    return JobRecord(
        job_id=sample_job_id,
        status="running",
        created_at=datetime.now(),
        started_at=datetime.now(),
        finished_at=None,
        question="Test question",
        input_log_path="data/sample.log",
        model="llama3",
        error=None,
        artifacts=[],
    )


@pytest.fixture
def sample_job_record_succeeded(sample_job_id):
    """Create sample job record with succeeded status."""
    started = datetime.now()
    finished = datetime.now()
    return JobRecord(
        job_id=sample_job_id,
        status="succeeded",
        created_at=started,
        started_at=started,
        finished_at=finished,
        question="Test question",
        input_log_path="data/sample.log",
        model="llama3",
        error=None,
        artifacts=[],
    )


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_check(self, client):
        """Test health endpoint returns ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestCreateJob:
    """Tests for POST /jobs endpoint."""

    @patch("api.routers.jobs.job_store")
    @patch("api.routers.jobs.job_runner")
    def test_create_job_returns_job_id(
        self, mock_runner, mock_store, client, sample_job_id, sample_job_record_queued
    ):
        """Test POST /jobs returns job_id immediately."""
        # Setup mocks
        mock_store.create_job.return_value = sample_job_record_queued
        mock_runner.run_job_background = MagicMock()

        # Create test log file if it doesn't exist
        os.makedirs("data", exist_ok=True)
        test_log_path = "data/test_sample.log"
        if not os.path.exists(test_log_path):
            with open(test_log_path, "w") as f:
                f.write("test log content\n")

        # Make request
        response = client.post(
            "/api/v1/jobs",
            json={
                "question": "Test question",
                "log_path": test_log_path,
                "model": "llama3",
            },
        )

        # Assertions
        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert data["job_id"] == sample_job_id
        assert data["status"] == "queued"
        assert "queued_at" in data
        assert "links" in data
        assert data["links"]["self"] == f"/api/v1/jobs/{sample_job_id}"

        # Verify job_store.create_job was called
        mock_store.create_job.assert_called_once()

    def test_create_job_without_log_path(self, client):
        """Test POST /jobs without log_path returns 400."""
        # Make request without log_path
        response = client.post(
            "/api/v1/jobs",
            json={
                "question": "Test question",
            },
        )

        # Should return 400 (validation error)
        assert response.status_code == 400

    def test_create_job_invalid_log_path(self, client):
        """Test POST /jobs with invalid log_path returns 400."""
        # Make request with invalid log_path
        response = client.post(
            "/api/v1/jobs",
            json={
                "question": "Test question",
                "log_path": "nonexistent/file.log",
            },
        )

        # Should return 400 (invalid log source)
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert data["detail"]["code"] == "invalid_log_source"


class TestGetJob:
    """Tests for GET /jobs/{job_id} endpoint."""

    @patch("api.routers.jobs.job_store")
    def test_get_job_queued(
        self, mock_store, client, sample_job_id, sample_job_record_queued
    ):
        """Test GET /jobs/{id} returns queued job."""
        mock_store.get_job.return_value = sample_job_record_queued

        response = client.get(f"/api/v1/jobs/{sample_job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == sample_job_id
        assert data["status"] == "queued"
        assert data["question"] == "Test question"
        assert data["started_at"] is None
        assert data["finished_at"] is None

    @patch("api.routers.jobs.job_store")
    def test_get_job_running(
        self, mock_store, client, sample_job_id, sample_job_record_running
    ):
        """Test GET /jobs/{id} returns running job."""
        mock_store.get_job.return_value = sample_job_record_running

        response = client.get(f"/api/v1/jobs/{sample_job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == sample_job_id
        assert data["status"] == "running"
        assert data["started_at"] is not None
        assert data["finished_at"] is None

    @patch("api.routers.jobs.job_store")
    def test_get_job_succeeded(
        self, mock_store, client, sample_job_id, sample_job_record_succeeded
    ):
        """Test GET /jobs/{id} returns succeeded job."""
        mock_store.get_job.return_value = sample_job_record_succeeded

        response = client.get(f"/api/v1/jobs/{sample_job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == sample_job_id
        assert data["status"] == "succeeded"
        assert data["started_at"] is not None
        assert data["finished_at"] is not None

    @patch("api.routers.jobs.job_store")
    def test_get_job_not_found(self, mock_store, client, sample_job_id):
        """Test GET /jobs/{id} returns 404 for nonexistent job."""
        mock_store.get_job.return_value = None

        response = client.get(f"/api/v1/jobs/{sample_job_id}")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert data["detail"]["code"] == "not_found"


class TestJobStatusFlow:
    """Test job status transitions: queued -> running -> succeeded."""

    @patch("api.routers.jobs.job_store")
    def test_job_status_flow(
        self,
        mock_store,
        client,
        sample_job_id,
        sample_job_record_queued,
        sample_job_record_running,
        sample_job_record_succeeded,
    ):
        """Test complete job status flow."""
        # Step 1: Job is queued
        mock_store.get_job.return_value = sample_job_record_queued
        response = client.get(f"/api/v1/jobs/{sample_job_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

        # Step 2: Job is running
        mock_store.get_job.return_value = sample_job_record_running
        response = client.get(f"/api/v1/jobs/{sample_job_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "running"

        # Step 3: Job succeeded
        mock_store.get_job.return_value = sample_job_record_succeeded
        response = client.get(f"/api/v1/jobs/{sample_job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "succeeded"
        assert data["finished_at"] is not None

    @patch("api.routers.jobs.job_store")
    @patch("api.routers.jobs.job_runner")
    def test_create_job_rag_mode_default(
        self, mock_runner, mock_store, client, sample_job_id, sample_job_record_queued
    ):
        """Test POST /jobs without mode defaults to 'rag' mode."""
        mock_store.create_job.return_value = sample_job_record_queued
        mock_runner.run_job_background = MagicMock()

        os.makedirs("data", exist_ok=True)
        test_log_path = "data/test_sample.log"
        if not os.path.exists(test_log_path):
            with open(test_log_path, "w") as f:
                f.write("test log content\n")

        # Make request without mode (should default to "rag")
        response = client.post(
            "/api/v1/jobs",
            json={
                "question": "Test question",
                "log_path": test_log_path,
            },
        )

        assert response.status_code == 201
        # Verify mode="rag" was passed to runner
        call_args = mock_runner.run_job_background.call_args
        assert call_args is not None
        assert call_args.kwargs.get("mode") == "rag"

    @patch("api.routers.jobs.job_store")
    @patch("api.routers.jobs.job_runner")
    def test_create_job_heuristic_mode(
        self, mock_runner, mock_store, client, sample_job_id, sample_job_record_queued
    ):
        """Test POST /jobs with mode='heuristic' passes mode correctly."""
        mock_store.create_job.return_value = sample_job_record_queued
        mock_runner.run_job_background = MagicMock()

        os.makedirs("data", exist_ok=True)
        test_log_path = "data/test_sample.log"
        if not os.path.exists(test_log_path):
            with open(test_log_path, "w") as f:
                f.write("test log content\n")

        # Make request with mode="heuristic"
        response = client.post(
            "/api/v1/jobs",
            json={
                "question": "Test question",
                "log_path": test_log_path,
                "mode": "heuristic",
            },
        )

        assert response.status_code == 201
        # Verify mode="heuristic" was passed to runner
        call_args = mock_runner.run_job_background.call_args
        assert call_args is not None
        assert call_args.kwargs.get("mode") == "heuristic"


class TestRAGModeArtifacts:
    """Tests for RAG mode artifact generation."""

    @patch("api.routers.jobs.job_store")
    def test_rag_mode_artifacts_present(
        self, mock_store, client, sample_job_id, sample_job_record_succeeded_with_artifacts
    ):
        """Test GET /jobs/{id} returns artifacts for RAG mode jobs."""
        mock_store.get_job.return_value = sample_job_record_succeeded_with_artifacts

        response = client.get(f"/api/v1/jobs/{sample_job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "succeeded"
        assert "artifacts" in data
        assert len(data["artifacts"]) > 0
        assert len(data["artifacts"]) >= 3  # Should have retrieval.json, findings.json, final_answer.md
        
        # Verify artifact names
        artifact_names = [a["name"] for a in data["artifacts"]]
        assert "retrieval.json" in artifact_names
        assert "findings.json" in artifact_names
        assert "final_answer.md" in artifact_names

    @patch("api.routers.jobs.job_store")
    def test_list_artifacts_rag_mode(
        self, mock_store, client, sample_job_id, sample_job_record_succeeded_with_artifacts
    ):
        """Test GET /jobs/{id}/artifacts returns artifacts list for RAG mode."""
        mock_store.get_job.return_value = sample_job_record_succeeded_with_artifacts

        response = client.get(f"/api/v1/jobs/{sample_job_id}/artifacts")

        assert response.status_code == 200
        data = response.json()
        assert "artifacts" in data
        assert len(data["artifacts"]) > 0
        assert len(data["artifacts"]) >= 3
        
        # Verify artifact metadata
        for artifact in data["artifacts"]:
            assert "name" in artifact
            assert "path" in artifact
            assert "size_bytes" in artifact
            assert "content_type" in artifact
            assert "download_url" in artifact
