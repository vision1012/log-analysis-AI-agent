"""
Job storage service for FastAPI.

Provides persistent job storage with atomic writes to avoid corruption.
Each job is stored in runs/<job_id>/job.json
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from api.config import get_runs_dir
from api.schemas.job import CreateJobRequest, JobArtifact, JobRecord, UpdateJobRequest


class JobStore:
    """
    Service for persistent job storage.

    Stores jobs in runs/<job_id>/job.json with atomic writes.
    """

    def __init__(self, runs_base_dir: Optional[str] = None):
        """
        Initialize job store.

        Args:
            runs_base_dir: Base directory for job storage. If None, uses config value.
        """
        if runs_base_dir is None:
            runs_base_dir = get_runs_dir()
        self.runs_base_dir = runs_base_dir
        os.makedirs(self.runs_base_dir, exist_ok=True)

    def _get_job_dir(self, job_id: str) -> str:
        """
        Get job directory path for a given job_id.

        Args:
            job_id: Job identifier.

        Returns:
            Full path to job directory.
        """
        return os.path.join(self.runs_base_dir, job_id)

    def _get_job_file(self, job_id: str) -> str:
        """
        Get job.json file path for a given job_id.

        Args:
            job_id: Job identifier.

        Returns:
            Full path to job.json file.
        """
        job_dir = self._get_job_dir(job_id)
        return os.path.join(job_dir, "job.json")

    def _atomic_write(self, file_path: str, data: Dict[str, Any]) -> None:
        """
        Write JSON data atomically (write temp file then rename).

        Args:
            file_path: Target file path.
            data: Dictionary to write as JSON.

        Raises:
            OSError: If file writing fails.
        """
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Write to temporary file in same directory
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=".tmp",
            dir=os.path.dirname(file_path),
            text=True,
        )

        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str, ensure_ascii=False)

            # Atomic rename
            os.replace(temp_path, file_path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def create_job(self, request: CreateJobRequest) -> JobRecord:
        """
        Create a new job record.

        Args:
            request: CreateJobRequest with question, input_log_path, model.

        Returns:
            JobRecord with generated job_id and created_at timestamp.
        """
        job_id = str(uuid4())
        created_at = datetime.now()

        job_record = JobRecord(
            job_id=job_id,
            status="queued",
            created_at=created_at,
            started_at=None,
            finished_at=None,
            question=request.question,
            input_log_path=request.input_log_path,
            model=request.model,
            mode=request.mode,
            error=None,
            artifacts=[],
            current_step=None,
            progress_pct=0,
            step_started_at=None,
            step_timeout_seconds=None,
            duration_ms=None,
            cancel_requested=False,
        )

        # Persist to disk
        job_file = self._get_job_file(job_id)
        self._atomic_write(job_file, job_record.model_dump())

        return job_record

    def update_job(self, job_id: str, updates: UpdateJobRequest) -> Optional[JobRecord]:
        """
        Update an existing job record.

        Args:
            job_id: Job identifier.
            updates: UpdateJobRequest with fields to update.

        Returns:
            Updated JobRecord, or None if job not found.
        """
        job_file = self._get_job_file(job_id)

        if not os.path.isfile(job_file):
            return None

        # Read existing job
        with open(job_file, "r", encoding="utf-8") as f:
            job_data = json.load(f)

        # Update fields
        update_dict = updates.model_dump(exclude_unset=True)
        job_data.update(update_dict)

        # Handle artifacts: if provided, replace; otherwise keep existing
        if updates.artifacts is not None:
            job_data["artifacts"] = [a.model_dump() for a in updates.artifacts]

        # Parse back to JobRecord to validate
        job_record = JobRecord(**job_data)

        # Persist atomically
        self._atomic_write(job_file, job_record.model_dump())

        return job_record

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """
        Get a job record by job_id.

        Args:
            job_id: Job identifier.

        Returns:
            JobRecord if found, None otherwise.
        """
        job_file = self._get_job_file(job_id)

        if not os.path.isfile(job_file):
            return None

        try:
            with open(job_file, "r", encoding="utf-8") as f:
                job_data = json.load(f)

            return JobRecord(**job_data)
        except Exception:
            return None

    def list_jobs(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[JobRecord]:
        """
        List all jobs, optionally filtered by status.

        Args:
            status: Optional status filter (queued/running/succeeded/failed).
            limit: Optional maximum number of jobs to return.
            offset: Number of jobs to skip (for pagination).

        Returns:
            List of JobRecord objects, sorted by created_at descending.
        """
        if not os.path.isdir(self.runs_base_dir):
            return []

        jobs: List[JobRecord] = []

        # Iterate through all job directories
        for item in os.listdir(self.runs_base_dir):
            job_dir = os.path.join(self.runs_base_dir, item)
            if not os.path.isdir(job_dir):
                continue

            job_file = os.path.join(job_dir, "job.json")
            if not os.path.isfile(job_file):
                continue

            try:
                with open(job_file, "r", encoding="utf-8") as f:
                    job_data = json.load(f)

                job_record = JobRecord(**job_data)

                # Apply status filter if provided
                if status and job_record.status != status:
                    continue

                jobs.append(job_record)
            except Exception:
                # Skip corrupted or invalid job files
                continue

        # Sort by created_at descending (newest first)
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        # Apply pagination
        if offset > 0:
            jobs = jobs[offset:]
        if limit is not None:
            jobs = jobs[:limit]

        return jobs

    def job_exists(self, job_id: str) -> bool:
        """
        Check if a job exists.

        Args:
            job_id: Job identifier.

        Returns:
            True if job exists, False otherwise.
        """
        job_file = self._get_job_file(job_id)
        return os.path.isfile(job_file)

    def add_artifact(
        self, job_id: str, name: str, path: str, content_type: str
    ) -> Optional[JobRecord]:
        """
        Add an artifact to a job.

        Args:
            job_id: Job identifier.
            name: Artifact name.
            path: Artifact file path.
            content_type: Content type (e.g., "application/json", "text/markdown").

        Returns:
            Updated JobRecord, or None if job not found.
        """
        job_record = self.get_job(job_id)
        if not job_record:
            return None

        # Check if artifact already exists
        existing_artifact = next(
            (a for a in job_record.artifacts if a.name == name), None
        )

        artifact = JobArtifact(name=name, path=path, content_type=content_type)

        if existing_artifact:
            # Update existing artifact
            job_record.artifacts = [
                artifact if a.name == name else a for a in job_record.artifacts
            ]
        else:
            # Add new artifact
            job_record.artifacts.append(artifact)

        # Persist update
        job_file = self._get_job_file(job_id)
        self._atomic_write(job_file, job_record.model_dump())

        return job_record

    def is_cancellation_requested(self, job_id: str) -> bool:
        """
        Check if cancellation has been requested for a job.

        Args:
            job_id: Job identifier.

        Returns:
            True if cancellation requested, False otherwise.
        """
        job_record = self.get_job(job_id)
        return job_record.cancel_requested if job_record else False
