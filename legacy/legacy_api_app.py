"""
================================================================================
LEGACY FILE: Do not use in production. Replaced by api/main.py
================================================================================

This file is kept for reference only. It contains the original single-file
FastAPI implementation that has been replaced by the modular API structure.

DO NOT RUN THIS FILE IN PRODUCTION.

Correct run command for production:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

This legacy file will be removed in a future release.
================================================================================

API application for the Log Analysis AI Agent.

Provides minimal, production-shaped REST endpoints to:
- start a log-analysis job
- query job status
- fetch the final markdown report
- list and download job artifacts
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from agent.runtime.job_models import JobRequest, JobStatus, ToolCall
from agent.runtime.storage import (
    read_job_state,
)
from agent.runtime.worker import run_job


API_PREFIX = "/api/v1"
JOBS_BASE_DIR = os.path.join("output", "jobs")


class ErrorCode(str):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    JOB_NOT_READY = "job_not_ready"
    INTERNAL_ERROR = "internal_error"
    DEPENDENCY_MISSING = "dependency_missing"
    INVALID_LOG_SOURCE = "invalid_log_source"


class APIError(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class StartJobRequestAPI(BaseModel):
    """
    API request model to start a new job.

    This is a thin wrapper that is translated into JobRequest for the worker.
    """

    query: str = Field(..., description="Natural language question or instruction.")
    log_path: Optional[str] = Field(
        default=None,
        description="Optional path to log file on the server accessible to the worker.",
    )
    mode: Literal["heuristic", "llm"] = Field(
        default="heuristic",
        description="Planning mode to use for the job.",
    )
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional execution options forwarded to the worker.",
    )


class StartJobResponseAPI(BaseModel):
    job_id: str
    status: JobStatus
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    links: Dict[str, str] = Field(default_factory=dict)


class ToolCallSummaryAPI(BaseModel):
    name: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    summary: Optional[str] = None


class JobSummaryAPI(BaseModel):
    job_id: str
    status: JobStatus
    query: Optional[str] = None
    mode: Optional[str] = None

    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    final_answer_preview: Optional[str] = None

    tool_calls: List[ToolCallSummaryAPI] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    links: Dict[str, str] = Field(default_factory=dict)


class ArtifactInfoAPI(BaseModel):
    name: str
    path: str
    size_bytes: Optional[int] = None
    content_type: Optional[str] = None
    created_at: Optional[datetime] = None
    download_url: str


class ListArtifactsResponseAPI(BaseModel):
    job_id: str
    artifacts: List[ArtifactInfoAPI]


app = FastAPI(
    title="Log Analysis AI Agent API",
    version="1.0.0",
    description="HTTP API for running log analysis jobs and retrieving results.",
)


def _job_dir(job_id: str) -> str:
    return os.path.join(JOBS_BASE_DIR, job_id)


def _ensure_job_exists(job_id: str) -> str:
    job_dir = _job_dir(job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(
            status_code=404,
            detail=APIError(
                code=ErrorCode.NOT_FOUND,
                message=f"Job '{job_id}' not found.",
            ).model_dump(),
        )
    return job_dir


@app.post(f"{API_PREFIX}/jobs", response_model=StartJobResponseAPI, status_code=201)
def start_job(payload: StartJobRequestAPI) -> StartJobResponseAPI:
    """
    Start a new log analysis job.

    Note:
        For now this runs the job synchronously via `run_job` and returns
        the final status once complete. The contract still exposes a
        polling-friendly interface and job state on disk.
    """
    if not payload.log_path:
        raise HTTPException(
            status_code=400,
            detail=APIError(
                code=ErrorCode.INVALID_LOG_SOURCE,
                message="log_path is required for now.",
            ).model_dump(),
        )

    if not os.path.isfile(payload.log_path):
        raise HTTPException(
            status_code=400,
            detail=APIError(
                code=ErrorCode.INVALID_LOG_SOURCE,
                message=f"Log file not found: {payload.log_path}",
            ).model_dump(),
        )

    # Construct JobRequest for the worker
    job_request = JobRequest(
        query=payload.query,
        file_paths=[payload.log_path],
    )

    try:
        job_result = run_job(job_request, mode=payload.mode)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=APIError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to start job: {exc}",
            ).model_dump(),
        ) from exc

    job_id = job_result.job_id
    timing = job_result.timing

    base_links = {
        "self": f"{API_PREFIX}/jobs/{job_id}",
        "report": f"{API_PREFIX}/jobs/{job_id}/report",
        "artifacts": f"{API_PREFIX}/jobs/{job_id}/artifacts",
    }

    return StartJobResponseAPI(
        job_id=job_id,
        status=job_result.status,
        queued_at=timing.started_at,
        started_at=timing.started_at,
        finished_at=timing.finished_at,
        links=base_links,
    )


@app.get(f"{API_PREFIX}/jobs/{{job_id}}", response_model=JobSummaryAPI)
def get_job(job_id: str = Path(..., description="Job identifier")) -> JobSummaryAPI:
    """
    Get high-level job status and summary.
    """
    job_dir = _ensure_job_exists(job_id)
    state = read_job_state(job_dir)
    if not state:
        raise HTTPException(
            status_code=404,
            detail=APIError(
                code=ErrorCode.NOT_FOUND,
                message=f"Job state for '{job_id}' not found.",
            ).model_dump(),
        )

    status: JobStatus = state.get("status", "failed")  # type: ignore[assignment]
    query = state.get("query")
    mode = state.get("mode")

    timing: Dict[str, Any] = state.get("timing", {})
    started_at_raw = timing.get("started_at")
    finished_at_raw = timing.get("finished_at")
    duration_ms = timing.get("duration_ms")

    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    started_at = _parse_dt(started_at_raw)
    finished_at = _parse_dt(finished_at_raw)

    final_answer = state.get("final_answer") or ""
    preview = final_answer[:200] if final_answer else None

    tool_calls_state: List[Dict[str, Any]] = state.get("tool_calls", [])
    tool_calls: List[ToolCallSummaryAPI] = []
    for tc in tool_calls_state:
        # tool_calls in job.json are compatible with ToolCall
        try:
            tool = ToolCall(**tc)
            tool_calls.append(
                ToolCallSummaryAPI(
                    name=tool.name,
                    status=tool.status,
                    started_at=tool.started_at,
                    finished_at=tool.finished_at,
                    summary=tool.summary,
                )
            )
        except Exception:
            # Fallback: best-effort mapping
            tool_calls.append(
                ToolCallSummaryAPI(
                    name=str(tc.get("name", "unknown")),
                    status=str(tc.get("status", "pending")),
                    started_at=None,
                    finished_at=None,
                    summary=str(tc.get("summary") or ""),
                )
            )

    errors: List[str] = state.get("errors", [])
    warnings: List[str] = state.get("warnings", [])

    links = {
        "self": f"{API_PREFIX}/jobs/{job_id}",
        "report": f"{API_PREFIX}/jobs/{job_id}/report",
        "artifacts": f"{API_PREFIX}/jobs/{job_id}/artifacts",
    }

    return JobSummaryAPI(
        job_id=job_id,
        status=status,
        query=query,
        mode=mode,
        queued_at=started_at,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        final_answer_preview=preview,
        tool_calls=tool_calls,
        errors=errors,
        warnings=warnings,
        links=links,
    )


@app.get(
    f"{API_PREFIX}/jobs/{{job_id}}/report",
    response_class=PlainTextResponse,
)
def get_report(job_id: str = Path(..., description="Job identifier")) -> PlainTextResponse:
    """
    Return the final markdown report for a job (final_answer.md).
    """
    job_dir = _ensure_job_exists(job_id)
    state = read_job_state(job_dir) or {}
    status = state.get("status", "failed")

    if status in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=APIError(
                code=ErrorCode.JOB_NOT_READY,
                message=f"Job '{job_id}' is not finished yet (status={status}).",
            ).model_dump(),
        )

    report_path = os.path.join(job_dir, "final_answer.md")
    if not os.path.isfile(report_path):
        raise HTTPException(
            status_code=404,
            detail=APIError(
                code=ErrorCode.NOT_FOUND,
                message=f"Report for job '{job_id}' not found.",
            ).model_dump(),
        )

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    return PlainTextResponse(content=content, media_type="text/markdown")


@app.get(f"{API_PREFIX}/jobs/{{job_id}}/artifacts", response_model=ListArtifactsResponseAPI)
def list_artifacts(job_id: str = Path(..., description="Job identifier")) -> ListArtifactsResponseAPI:
    """
    List known artifacts for a job.
    """
    job_dir = _ensure_job_exists(job_id)

    # Known artifacts at job root
    known_names = [
        "job.json",
        "retrieval.json",
        "findings.json",
        "final_answer.md",
    ]

    artifacts: List[ArtifactInfoAPI] = []
    for name in known_names:
        path = os.path.join(job_dir, name)
        if not os.path.isfile(path):
            continue

        stat = os.stat(path)
        size_bytes = stat.st_size
        created_at = datetime.fromtimestamp(stat.st_mtime)

        if name.endswith(".json"):
            content_type = "application/json"
        elif name.endswith(".md"):
            content_type = "text/markdown"
        else:
            content_type = "application/octet-stream"

        artifacts.append(
            ArtifactInfoAPI(
                name=name,
                path=f"jobs/{job_id}/{name}",
                size_bytes=size_bytes,
                content_type=content_type,
                created_at=created_at,
                download_url=f"{API_PREFIX}/jobs/{job_id}/artifacts/{name}",
            )
        )

    return ListArtifactsResponseAPI(job_id=job_id, artifacts=artifacts)


@app.get(f"{API_PREFIX}/jobs/{{job_id}}/artifacts/{{artifact_name}}")
def download_artifact(
    job_id: str = Path(..., description="Job identifier"),
    artifact_name: str = Path(..., description="Artifact file name"),
) -> FileResponse:
    """
    Download a specific artifact by name.

    Supported names:
        - job.json
        - retrieval.json
        - findings.json
        - final_answer.md
    """
    job_dir = _ensure_job_exists(job_id)

    # Basic sanitization: only allow simple file names, no path separators
    if "/" in artifact_name or "\\" in artifact_name or ".." in artifact_name:
        raise HTTPException(
            status_code=400,
            detail=APIError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid artifact name.",
            ).model_dump(),
        )

    allowed_names = {"job.json", "retrieval.json", "findings.json", "final_answer.md"}
    if artifact_name not in allowed_names:
        raise HTTPException(
            status_code=404,
            detail=APIError(
                code=ErrorCode.NOT_FOUND,
                message=f"Artifact '{artifact_name}' not found or not allowed.",
            ).model_dump(),
        )

    path = os.path.join(job_dir, artifact_name)
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=404,
            detail=APIError(
                code=ErrorCode.NOT_FOUND,
                message=f"Artifact '{artifact_name}' not found for job '{job_id}'.",
            ).model_dump(),
        )

    if artifact_name.endswith(".json"):
        media_type = "application/json"
    elif artifact_name.endswith(".md"):
        media_type = "text/markdown"
    else:
        media_type = "application/octet-stream"

    return FileResponse(path=path, media_type=media_type, filename=artifact_name)
