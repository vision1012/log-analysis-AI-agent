"""
Centralized path management for the API.

All paths are absolute and independent of current working directory.
This ensures background tasks and different execution contexts use consistent paths.
"""

from __future__ import annotations

from pathlib import Path

# Base directory: project root (2 levels up from api/core/paths.py)
BASE_DIR = Path(__file__).resolve().parents[2]

# Core directories
RUNS_DIR = BASE_DIR / "runs"
OUTPUT_JOBS_DIR = BASE_DIR / "output" / "jobs"
ARTIFACTS_DIR = BASE_DIR / "artifacts"

# Ensure directories exist
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_JOBS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def get_job_output_dir(job_id: str) -> Path:
    """
    Get absolute path to job output directory.

    Args:
        job_id: Job identifier.

    Returns:
        Absolute Path to output/jobs/<job_id>/
    """
    job_dir = OUTPUT_JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def get_job_artifacts_dir(job_id: str) -> Path:
    """
    Get absolute path to job artifacts directory.

    Args:
        job_id: Job identifier.

    Returns:
        Absolute Path to artifacts/<job_id>/
    """
    artifacts_dir = ARTIFACTS_DIR / job_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return artifacts_dir


def get_job_run_dir(job_id: str) -> Path:
    """
    Get absolute path to job run directory (for logs and job.json).

    Args:
        job_id: Job identifier.

    Returns:
        Absolute Path to runs/<job_id>/
    """
    run_dir = RUNS_DIR / job_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
