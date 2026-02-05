"""
Pydantic schemas for job-related API requests and responses.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Job status enumeration."""
    
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorCode(str):
    """Error code constants."""

    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    JOB_NOT_READY = "job_not_ready"
    INTERNAL_ERROR = "internal_error"
    DEPENDENCY_MISSING = "dependency_missing"
    INVALID_LOG_SOURCE = "invalid_log_source"


class APIError(BaseModel):
    """API error response model."""

    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class CreateJobAPIRequest(BaseModel):
    """
    Production API request model to create a new log analysis job.
    
    Matches the production contract: {question, log_path?, top_k?, model?, mode?}
    """

    question: str = Field(..., description="Natural language question or instruction")
    log_path: Optional[str] = Field(
        None, description="Path to log file (absolute or relative to backend)"
    )
    top_k: Optional[int] = Field(
        default=8, description="Number of top chunks to retrieve (for RAG mode)"
    )
    model: Optional[str] = Field(
        default=None, description="Ollama model name (e.g., 'llama3'). Defaults to env var or 'llama3'"
    )
    mode: Literal["heuristic", "rag"] = Field(
        default="rag",
        description="Execution mode: 'rag' runs full RAG pipeline (retrieval, investigation, reporting) and generates artifacts. 'heuristic' uses rule-based planning without RAG agents."
    )


class StartJobRequest(BaseModel):
    """
    Request model to start a new log analysis job.
    """

    query: str = Field(..., description="Natural language question or instruction")
    log_path: Optional[str] = Field(
        None, description="Path to log file (absolute or relative to backend)"
    )
    log_source_id: Optional[str] = Field(
        None, description="Logical log source identifier (future use)"
    )
    mode: Literal["heuristic", "llm"] = Field(
        default="heuristic", description="Planning mode"
    )
    options: Dict[str, Any] = Field(
        default_factory=dict, description="Additional job options"
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate that at least one log source is provided."""
        if not self.log_path and not self.log_source_id:
            raise ValueError("Either 'log_path' or 'log_source_id' must be provided")


class StartJobResponse(BaseModel):
    """Response model for job creation."""

    job_id: str
    status: str
    queued_at: datetime
    estimated_start_time: Optional[datetime] = None
    links: Dict[str, str]


class CancelJobResponse(BaseModel):
    """Response model for job cancellation."""

    job_id: str
    status: str
    cancelled: bool
    message: str


class ToolCallSummary(BaseModel):
    """Summary of a tool call execution."""

    name: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    summary: Optional[str] = None


class JobSummary(BaseModel):
    """Job status and summary response model."""

    job_id: str
    status: str
    query: str
    mode: str
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    final_answer_preview: Optional[str] = None
    tool_calls: List[ToolCallSummary] = Field(default_factory=list)
    errors: List[APIError] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    links: Dict[str, str] = Field(default_factory=dict)


class ArtifactInfo(BaseModel):
    """Artifact metadata model."""

    name: str
    path: str
    size_bytes: Optional[int] = None
    content_type: Optional[str] = None
    created_at: Optional[datetime] = None
    download_url: str


class ListArtifactsResponse(BaseModel):
    """Response model for listing job artifacts."""

    job_id: str
    artifacts: List[ArtifactInfo]


# JobStore schemas for persistent job storage
class JobArtifact(BaseModel):
    """Artifact metadata for JobStore."""

    name: str
    path: str
    content_type: str


class JobRecord(BaseModel):
    """
    Complete job record for persistent storage.

    Stored in runs/<job_id>/job.json
    """

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    question: str
    input_log_path: Optional[str] = None
    model: str  # Ollama model name (e.g., "llama3")
    mode: Literal["heuristic", "rag"] = Field(
        default="rag",
        description="Execution mode: 'rag' runs full RAG pipeline, 'heuristic' uses rule-based planning"
    )
    error: Optional[str] = None
    artifacts: List[JobArtifact] = Field(default_factory=list)
    
    # Progress tracking
    current_step: Optional[str] = Field(
        default=None,
        description="Current pipeline step: validate_input, retrieve_context, investigate, generate_report, write_artifacts"
    )
    progress_pct: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Progress percentage (0-100)"
    )
    step_started_at: Optional[datetime] = Field(
        default=None,
        description="When the current step started"
    )
    step_timeout_seconds: Optional[int] = Field(
        default=None,
        description="Timeout in seconds for the current step"
    )
    duration_ms: Optional[int] = Field(
        default=None,
        description="Total duration in milliseconds"
    )
    
    # Cancellation support
    cancel_requested: bool = Field(
        default=False,
        description="Flag indicating if cancellation was requested"
    )


class CreateJobRequest(BaseModel):
    """Request to create a new job."""

    question: str
    input_log_path: Optional[str] = None
    model: str = Field(default="llama3", description="Ollama model name")
    mode: Literal["heuristic", "rag"] = Field(
        default="rag",
        description="Execution mode: 'rag' runs full RAG pipeline, 'heuristic' uses rule-based planning"
    )


class UpdateJobRequest(BaseModel):
    """Request to update job fields."""

    status: Optional[Literal["queued", "running", "succeeded", "failed", "cancelled"]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    artifacts: Optional[List[JobArtifact]] = None
    current_step: Optional[str] = None
    progress_pct: Optional[int] = Field(None, ge=0, le=100)
    step_started_at: Optional[datetime] = None
    step_timeout_seconds: Optional[int] = None
    duration_ms: Optional[int] = None
    cancel_requested: Optional[bool] = None
    mode: Optional[Literal["heuristic", "rag"]] = None