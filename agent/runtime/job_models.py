"""
Job Request/Response Models

Pydantic models for job lifecycle: JobRequest (input) and JobResult (output).
These are separate from ToolResult schema and represent the full job execution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


JobStatus = Literal["queued", "running", "succeeded", "failed"]
ToolCallStatus = Literal["pending", "running", "success", "error"]


class JobOptions(BaseModel):
    """
    Options that control how the worker should process a job.

    This is kept intentionally generic so that:
      - Java/Spring can pass options through as JSON
      - Python worker can evolve without breaking the contract
    """

    model_config = ConfigDict(extra="forbid")

    use_llm_planner: bool = Field(
        default=True,
        description="If True, use LLM-based planner; otherwise use heuristic/rule-based planning.",
    )
    max_tool_calls: int = Field(
        default=5,
        ge=1,
        description="Maximum number of tool calls allowed for this job.",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Overall timeout for the job in seconds.",
    )
    allow_network: bool = Field(
        default=False,
        description="If True, tools are allowed to use network (if implemented).",
    )
    top_k_chunks: int = Field(
        default=20,
        ge=1,
        description="Number of top retrieved chunks for RAG (when enabled).",
    )


class ToolCall(BaseModel):
    """
    A single tool invocation within a job.

    Note: The actual tool result is stored in JobResult.tool_results
    as a plain dict (ToolResult) for maximum flexibility.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Logical tool name (e.g. 'run_log_summary').")
    status: ToolCallStatus = Field(
        default="pending",
        description="Execution status of this tool call.",
    )
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments passed to the tool.",
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the tool call started.",
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the tool call finished.",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Short human-readable summary of what this tool did.",
    )


class ArtifactRef(BaseModel):
    """
    Reference to an artifact produced during a job.

    This is separate from ToolArtifact (per-tool) so that the worker
    can aggregate all artifacts at the job level.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["file", "json", "text"] = Field(
        default="file",
        description="Type of artifact.",
    )
    name: str = Field(
        ...,
        description="Human-readable name of the artifact.",
    )
    path: str = Field(
        ...,
        description="Filesystem path where the artifact is stored.",
    )
    from_tool: Optional[str] = Field(
        default=None,
        description="Name of the tool that produced this artifact (e.g. 'run_log_summary').",
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional description to help UI/agent display this artifact.",
    )


class RunTiming(BaseModel):
    """
    Timing information for the entire job.
    """

    model_config = ConfigDict(extra="forbid")

    started_at: Optional[datetime] = Field(
        default=None,
        description="When the job started processing.",
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description="When the job finished (success or failure).",
    )
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total duration in milliseconds, if available.",
    )


class JobContext(BaseModel):
    """
    Runtime context for a job execution.
    
    Contains job-scoped paths and file mappings that ensure:
    - All artifacts are written under the job directory
    - Input files are copied to a stable location
    - Tools never read from random paths
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(
        ...,
        description="Unique identifier for the job (UUID string).",
    )
    job_dir: str = Field(
        ...,
        description="Full path to the job directory (output/jobs/<job_id>/).",
    )
    artifacts_dir: str = Field(
        ...,
        description="Full path to the artifacts directory (output/jobs/<job_id>/artifacts/).",
    )
    inputs_dir: str = Field(
        ...,
        description="Full path to the inputs directory (output/jobs/<job_id>/inputs/).",
    )
    input_files: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Mapping from original file path to copied path inside job directory. "
            "Key: original path, Value: copied path in inputs_dir."
        ),
    )


class JobRequest(BaseModel):
    """
    Incoming request to run a log-analysis job.

    This is what your API/CLI will construct and pass to the worker.
    The worker will generate `job_id` and produce a JobResult.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        description="Natural language question or instruction from the user.",
    )
    file_paths: List[str] = Field(
        default_factory=list,
        description="List of log file paths to analyze.",
    )
    options: JobOptions = Field(
        default_factory=JobOptions,
        description="Execution options that control how the job runs.",
    )

    def generate_job_id(self) -> str:
        """
        Helper to generate a new job_id (UUID4 as a string).
        Can be used by the worker when creating the job.
        """
        return str(uuid4())


class JobResult(BaseModel):
    """
    Final result of a job executed by the worker.

    This is what will be persisted to `output/jobs/<job_id>/job.json`
    and returned via API/CLI. All fields are JSON-serializable.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(
        ...,
        description="Unique identifier for the job (UUID string).",
    )
    status: JobStatus = Field(
        ...,
        description="Final status of the job.",
    )

    # High-level answer / summary
    final_answer: Optional[str] = Field(
        default=None,
        description="Final natural language answer composed by the LLM/planner.",
    )

    # Tool executions
    tool_calls: List[ToolCall] = Field(
        default_factory=list,
        description="Metadata about tool calls made during the job.",
    )
    tool_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of raw ToolResult dictionaries (one per tool call), "
            "already validated/normalized via validate_tool_result()."
        ),
    )

    # Artifacts produced across all tools
    artifacts: List[ArtifactRef] = Field(
        default_factory=list,
        description="All artifacts produced during the job (files, JSON, text).",
    )

    # Warnings and errors at the job level (not per-tool)
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings encountered while processing the job.",
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Fatal or high-level errors explaining job failure.",
    )

    # Timing information
    timing: RunTiming = Field(
        default_factory=RunTiming,
        description="Timing information for the job run.",
    )

    # Optional free-form metadata for debugging or future features
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata for debugging, tracing, or future extensions.",
    )
