"""
Storage Module

Helpers for creating job directories, writing job state, and managing artifacts.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from agent.runtime.job_models import ArtifactRef, JobContext


def create_job_dir(base: str = "output/jobs") -> Tuple[str, str]:
    """
    Create a new job directory with a unique job_id.

    Args:
        base: Base directory path for jobs. Default: "output/jobs".

    Returns:
        Tuple of (job_id, job_dir) where job_dir is the full path to the created directory.

    Raises:
        OSError: If directory creation fails.
    """
    from uuid import uuid4

    job_id = str(uuid4())
    job_dir = os.path.join(base, job_id)

    os.makedirs(job_dir, exist_ok=True)

    return job_id, job_dir


def create_job_context(job_id: str, job_dir: str) -> JobContext:
    """
    Create a JobContext with all required directories.

    Creates the following structure:
        output/jobs/<job_id>/
        output/jobs/<job_id>/artifacts/
        output/jobs/<job_id>/inputs/

    Args:
        job_id: Unique identifier for the job.
        job_dir: Full path to the job directory.

    Returns:
        JobContext with all paths initialized.

    Raises:
        OSError: If directory creation fails.
    """
    artifacts_dir = os.path.join(job_dir, "artifacts")
    inputs_dir = os.path.join(job_dir, "inputs")

    os.makedirs(artifacts_dir, exist_ok=True)
    os.makedirs(inputs_dir, exist_ok=True)

    return JobContext(
        job_id=job_id,
        job_dir=job_dir,
        artifacts_dir=artifacts_dir,
        inputs_dir=inputs_dir,
        input_files={},
    )


def copy_input_files(context: JobContext, original_paths: list[str]) -> JobContext:
    """
    Copy input files into the job's inputs directory and update context.

    Args:
        context: JobContext to update.
        original_paths: List of original file paths to copy.

    Returns:
        Updated JobContext with input_files mapping populated.

    Raises:
        FileNotFoundError: If any input file doesn't exist.
        OSError: If file copying fails.
    """
    input_files: Dict[str, str] = {}

    for original_path in original_paths:
        if not os.path.isfile(original_path):
            raise FileNotFoundError(f"Input file not found: {original_path}")

        # Generate a safe filename (use basename, handle collisions)
        original_basename = os.path.basename(original_path)
        copied_path = os.path.join(context.inputs_dir, original_basename)

        # Handle collisions by appending a counter
        counter = 1
        base_name, ext = os.path.splitext(original_basename)
        while os.path.exists(copied_path):
            copied_path = os.path.join(
                context.inputs_dir, f"{base_name}_{counter}{ext}"
            )
            counter += 1

        # Copy the file
        shutil.copy2(original_path, copied_path)

        # Store mapping
        input_files[original_path] = copied_path

    # Update context with new mapping
    context.input_files = input_files
    return context


def write_job_state(job_dir: str, payload: Dict[str, Any]) -> str:
    """
    Write job state to job.json in the job directory.

    Args:
        job_dir: Path to the job directory.
        payload: Dictionary to write (should be JSON-serializable, e.g. JobResult.model_dump()).

    Returns:
        Full path to the written job.json file.

    Raises:
        OSError: If file writing fails.
        TypeError: If payload is not JSON-serializable.
    """
    job_file = os.path.join(job_dir, "job.json")

    os.makedirs(job_dir, exist_ok=True)

    with open(job_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return job_file


def read_job_state(job_dir: str) -> Dict[str, Any] | None:
    """
    Read job state from job.json in the job directory.

    Args:
        job_dir: Path to the job directory.

    Returns:
        Dictionary with job state, or None if file doesn't exist.
    """
    job_file = os.path.join(job_dir, "job.json")

    if not os.path.isfile(job_file):
        return None

    try:
        with open(job_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def update_job_state(job_dir: str, updates: Dict[str, Any]) -> str:
    """
    Update job state by merging updates into existing state.

    Args:
        job_dir: Path to the job directory.
        updates: Dictionary of fields to update.

    Returns:
        Full path to the updated job.json file.
    """
    existing_state = read_job_state(job_dir) or {}
    updated_state = {**existing_state, **updates}
    return write_job_state(job_dir, updated_state)


def get_job_status(job_dir: str) -> str | None:
    """
    Get current job status from job.json.

    Args:
        job_dir: Path to the job directory.

    Returns:
        Job status string ("queued", "running", "succeeded", "failed"), or None if not found.
    """
    state = read_job_state(job_dir)
    if state:
        return state.get("status")
    return None


def check_artifact_exists(job_dir: str, artifact_name: str) -> bool:
    """
    Check if an artifact file exists in the job directory.

    Args:
        job_dir: Path to the job directory.
        artifact_name: Name of artifact file (e.g., "retrieval.json", "findings.json").

    Returns:
        True if artifact exists, False otherwise.
    """
    artifact_path = os.path.join(job_dir, artifact_name)
    return os.path.isfile(artifact_path)


def get_existing_artifacts(job_dir: str) -> List[str]:
    """
    Get list of existing artifact files in the job directory.

    Args:
        job_dir: Path to the job directory.

    Returns:
        List of artifact file names that exist.
    """
    artifacts = []
    artifact_names = ["retrieval.json", "findings.json", "final_answer.md"]

    for artifact_name in artifact_names:
        if check_artifact_exists(job_dir, artifact_name):
            artifacts.append(artifact_name)

    # Also check tool_results directory
    tool_results_dir = os.path.join(job_dir, "tool_results")
    if os.path.isdir(tool_results_dir):
        for filename in os.listdir(tool_results_dir):
            if filename.endswith(".json"):
                artifacts.append(f"tool_results/{filename}")

    return artifacts


def write_tool_result(
    job_dir: str, tool_index: int, tool_name: str, tool_result: Dict[str, Any]
) -> str | None:
    """
    Write a single tool result to a JSON file.

    Creates: output/jobs/<job_id>/tool_results/<n>_<toolname>.json

    Args:
        job_dir: Path to the job directory.
        tool_index: Zero-based index of the tool call (for ordering).
        tool_name: Name of the tool (e.g. "run_log_summary").
        tool_result: Validated ToolResult dictionary to write.

    Returns:
        Full path to the written file, or None if writing failed.

    Note:
        Never raises exceptions - returns None on failure for graceful error handling.
    """
    try:
        tool_results_dir = os.path.join(job_dir, "tool_results")
        os.makedirs(tool_results_dir, exist_ok=True)

        # Sanitize tool_name for filename (remove any path separators)
        safe_tool_name = tool_name.replace("/", "_").replace("\\", "_")

        # Format: <n>_<toolname>.json (e.g., "0_run_log_summary.json")
        filename = f"{tool_index:03d}_{safe_tool_name}.json"
        file_path = os.path.join(tool_results_dir, filename)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(tool_result, f, indent=2, default=str)

        return file_path
    except Exception:
        # Never crash on file IO errors - return None for caller to handle
        return None


def write_plan(job_dir: str, plan: Any) -> str | None:
    """
    Write execution plan to plan.json in the job directory.

    Creates: output/jobs/<job_id>/plan.json

    Args:
        job_dir: Path to the job directory.
        plan: Plan object (Pydantic model) to write.

    Returns:
        Full path to the written file, or None if writing failed.

    Note:
        Never raises exceptions - returns None on failure for graceful error handling.
    """
    try:
        plan_file = os.path.join(job_dir, "plan.json")
        
        # Convert Pydantic model to dict (handles datetime serialization)
        if hasattr(plan, "model_dump"):
            plan_dict = plan.model_dump()
        else:
            plan_dict = plan

        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan_dict, f, indent=2, default=str)

        return plan_file
    except Exception:
        # Never crash on file IO errors - return None for caller to handle
        return None


def artifact_ref_from_path(
    path: str,
    from_tool: str | None = None,
    description: str | None = None,
) -> ArtifactRef:
    """
    Create an ArtifactRef from a filesystem path.

    Args:
        path: Filesystem path to the artifact file.
        from_tool: Optional tool name that produced this artifact.
        description: Optional description of the artifact.

    Returns:
        ArtifactRef object with type, name, and path populated.
    """
    path_obj = Path(path)
    name = path_obj.name

    artifact_type = "file"
    if path.endswith(".json"):
        artifact_type = "json"
    elif path.endswith((".txt", ".log")):
        artifact_type = "text"

    return ArtifactRef(
        type=artifact_type,
        name=name,
        path=path,
        from_tool=from_tool,
        description=description,
    )
