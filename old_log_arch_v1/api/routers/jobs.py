"""
Production-style FastAPI endpoints for job management.

Handles job creation, status queries, report retrieval, and artifact management.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from api.config import settings
from api.core.paths import ARTIFACTS_DIR, OUTPUT_JOBS_DIR
from api.schemas.job import (
    APIError,
    ArtifactInfo,
    CancelJobResponse,
    CreateJobAPIRequest,
    CreateJobRequest,
    ErrorCode,
    JobRecord,
    JobSummary,
    ListArtifactsResponse,
    StartJobResponse,
    UpdateJobRequest,
)
from api.services.job_store import JobStore
from api.services.runner import JobRunner
from api.schemas.job import CancelJobResponse

router = APIRouter()

# Initialize services
job_store = JobStore()
job_runner = JobRunner(job_store=job_store)


def _build_job_links(job_id: str) -> dict[str, str]:
    """Build HATEOAS links for a job."""
    return {
        "self": f"/api/v1/jobs/{job_id}",
        "report": f"/api/v1/jobs/{job_id}/report",
        "artifacts": f"/api/v1/jobs/{job_id}/artifacts",
    }


def _validate_job_exists(job_id: str) -> JobRecord:
    """
    Validate that a job exists and return its record.

    Args:
        job_id: Job identifier.

    Returns:
        JobRecord if found.

    Raises:
        HTTPException: 404 if job not found.
    """
    job_record = job_store.get_job(job_id)
    if not job_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": f"Job not found: {job_id}",
            },
        )
    return job_record


def _get_content_type(filename: str) -> str:
    """
    Determine content type from filename.

    Args:
        filename: File name.

    Returns:
        Content type string.
    """
    ext = os.path.splitext(filename)[1].lower()
    content_types = {
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".log": "text/plain",
    }
    return content_types.get(ext, "application/octet-stream")


def _get_artifacts_from_job(job_record: JobRecord) -> List[ArtifactInfo]:
    """
    Build ArtifactInfo list from JobRecord artifacts.

    Artifacts are stored in artifacts/<job_id>/ directory and registered in JobRecord.

    Args:
        job_record: JobRecord with artifacts.

    Returns:
        List of ArtifactInfo objects with download URLs, names, relative paths, and sizes.
    """
    artifacts: List[ArtifactInfo] = []

    for artifact in job_record.artifacts:
        # Resolve artifact path (handle both absolute and relative paths)
        artifact_path = artifact.path
        if not os.path.isabs(artifact_path):
            # If relative, resolve from current working directory
            artifact_path = os.path.join(os.getcwd(), artifact_path)
        
        # Check if file exists
        if os.path.isfile(artifact_path):
            stat = os.stat(artifact_path)
            # Use relative path from repo root for API response
            relative_path = os.path.relpath(artifact_path, os.getcwd())
            artifacts.append(
                ArtifactInfo(
                    name=artifact.name,
                    path=relative_path,
                    size_bytes=stat.st_size,
                    content_type=artifact.content_type,
                    created_at=datetime.fromtimestamp(stat.st_mtime),
                    download_url=f"/api/v1/jobs/{job_record.job_id}/artifacts/{artifact.name}",
                )
            )

    return artifacts


def _find_artifact_path(job_record: JobRecord, artifact_name: str) -> Optional[str]:
    """
    Find artifact file path from JobRecord (artifacts/<job_id>/).

    Args:
        job_record: JobRecord to search.
        artifact_name: Name of artifact to find.

    Returns:
        Absolute file path if found, None otherwise.
    """
    # Check JobRecord artifacts (should point to artifacts/<job_id>/)
    for artifact in job_record.artifacts:
        if artifact.name == artifact_name:
            # Resolve path (handle both absolute and relative)
            artifact_path = artifact.path
            if not os.path.isabs(artifact_path):
                artifact_path = os.path.join(os.getcwd(), artifact_path)
            
            if os.path.isfile(artifact_path):
                return artifact_path

    # Fallback: check artifacts directory directly (using absolute path)
    artifacts_dir = ARTIFACTS_DIR / job_record.job_id
    artifact_path = artifacts_dir / artifact_name
    if artifact_path.is_file():
        return str(artifact_path)

    return None


@router.post("/jobs", response_model=StartJobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: CreateJobAPIRequest, background_tasks: BackgroundTasks
) -> StartJobResponse:
    """
    Create a new log analysis job.

    Request body:
        - question (required): Natural language question
        - log_path (optional): Path to log file
        - top_k (optional): Number of chunks to retrieve (default: 8, for RAG mode)
        - model (optional): Ollama model name (default: llama3)
        - mode (optional): Execution mode - "rag" (default) runs full RAG pipeline with artifacts, "heuristic" uses rule-based planning without RAG agents

    Returns job_id immediately. Job runs asynchronously in background.
    """
    try:
        # Validate log_path exists if provided
        if request.log_path and not os.path.isfile(request.log_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": ErrorCode.INVALID_LOG_SOURCE,
                    "message": f"Log file not found: {request.log_path}",
                },
            )

        # Determine model name (from request or config)
        model = request.model or settings.ollama_model

        # Get mode from request (defaults to "rag" if not specified)
        mode = request.mode

        # Create job in JobStore (status: queued)
        create_request = CreateJobRequest(
            question=request.question,
            input_log_path=request.log_path,
            model=model,
            mode=mode,
        )
        job_record = job_store.create_job(create_request)

        # Trigger background job execution
        background_tasks.add_task(
            job_runner.run_job_background,
            job_id=job_record.job_id,
            question=request.question,
            input_log_path=request.log_path,
            model=model,
            mode=mode,
        )

        return StartJobResponse(
            job_id=job_record.job_id,
            status=job_record.status,
            queued_at=job_record.created_at,
            estimated_start_time=None,
            links=_build_job_links(job_record.job_id),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": str(e),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.INTERNAL_ERROR,
                "message": f"Failed to create job: {str(e)}",
            },
        )


@router.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job(job_id: str = Path(..., description="Job identifier")) -> JobRecord:
    """
    Get full job state.

    Returns complete JobRecord with all fields including status, timestamps,
    question, model, error (if any), and artifacts list.
    """
    return _validate_job_exists(job_id)


@router.get("/jobs/{job_id}/report")
async def get_job_report(
    job_id: str = Path(..., description="Job identifier")
) -> Response:
    """
    Get final markdown report for a completed job.

    Returns markdown content from final_answer.md.
    Returns 404 if report file is missing.
    """
    # Validate job exists
    job_record = _validate_job_exists(job_id)

    # Check if job is completed
    if job_record.status not in ["succeeded", "failed"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": ErrorCode.JOB_NOT_READY,
                "message": f"Job is not ready (status: {job_record.status})",
            },
        )

    # Find report file in artifacts directory first, then fallback to output directory
    artifacts_dir = ARTIFACTS_DIR / job_id
    report_path = artifacts_dir / "final_answer.md"
    
    # Fallback to output directory if not in artifacts
    if not report_path.is_file():
        pipeline_job_dir = OUTPUT_JOBS_DIR / job_id
        report_path = pipeline_job_dir / "final_answer.md"

    if not report_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": "Report not found (final_answer.md)",
            },
        )

    # Stream the file with correct content type
    return FileResponse(
        str(report_path),
        media_type="text/markdown; charset=utf-8",
        filename="final_answer.md",
    )


@router.get("/jobs/{job_id}/artifacts", response_model=ListArtifactsResponse)
async def list_job_artifacts(
    job_id: str = Path(..., description="Job identifier")
) -> ListArtifactsResponse:
    """
    List all artifacts for a job with download URLs.

    Returns list of artifacts with metadata including name, path, size,
    content type, creation time, and download URL.
    """
    # Validate job exists and get record
    job_record = _validate_job_exists(job_id)

    # Build artifacts list from JobRecord and pipeline output
    artifacts = _get_artifacts_from_job(job_record)

    return ListArtifactsResponse(job_id=job_id, artifacts=artifacts)


@router.get("/jobs/{job_id}/artifacts/{artifact_name}")
async def download_artifact(
    job_id: str = Path(..., description="Job identifier"),
    artifact_name: str = Path(..., description="Artifact file name"),
) -> FileResponse:
    """
    Stream a specific artifact file with correct content-type.

    Allowed artifacts: retrieval.json, findings.json, final_answer.md, plan.json, pipeline_job.json

    Returns the file with appropriate content-type headers for streaming.
    """
    # Validate job exists
    _validate_job_exists(job_id)

    # Sanitize artifact name (prevent directory traversal)
    if "/" in artifact_name or "\\" in artifact_name or ".." in artifact_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "Invalid artifact name",
            },
        )

    # Allowed artifact names
    allowed_artifacts = [
        "retrieval.json",
        "findings.json",
        "final_answer.md",
        "job.json",
        "plan.json",
    ]

    if artifact_name not in allowed_artifacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": f"Invalid artifact name. Allowed: {', '.join(allowed_artifacts)}",
            },
        )

    # Get job record to find artifact
    job_record = _validate_job_exists(job_id)
    artifact_path = _find_artifact_path(job_record, artifact_name)

    if not artifact_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": f"Artifact not found: {artifact_name}",
            },
        )

    # Determine content type
    content_type = _get_content_type(artifact_name)

    # Stream file with correct content-type
    return FileResponse(
        artifact_path,
        media_type=content_type,
        filename=artifact_name,
    )


@router.post("/jobs/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_job(
    job_id: str = Path(..., description="Job identifier")
) -> CancelJobResponse:
    """
    Cancel a running or queued job.

    Only works if job is in "queued" or "running" status.
    Sets cancel_requested flag, which the pipeline runner checks between steps.
    """
    job_record = _validate_job_exists(job_id)

    # Only allow cancellation if job is queued or running
    if job_record.status not in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": f"Cannot cancel job with status '{job_record.status}'. Only queued or running jobs can be cancelled.",
            },
        )

    # Request cancellation via JobStore
    updated_record = job_store.request_cancellation(job_id)
    if not updated_record:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.INTERNAL_ERROR,
                "message": "Failed to request cancellation",
            },
        )

    # If job was queued, mark it as cancelled immediately
    # If job was running, it will be marked as cancelled by the runner
    if updated_record.status == "queued":
        job_store.update_job(
            job_id,
            UpdateJobRequest(
                status="cancelled",
                finished_at=datetime.now(),
            ),
        )
        updated_record = job_store.get_job(job_id)

    return CancelJobResponse(
        job_id=job_id,
        status=updated_record.status if updated_record else "cancelled",
        cancelled=True,
        message=f"Job cancellation requested. Status: {updated_record.status if updated_record else 'cancelled'}",
    )
