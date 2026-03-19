"""
Job-specific logging utilities.

Writes logs to runs/<job_id>/run.log for each job execution.
Uses standard library only.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional


class JobLogger:
    """
    Logger that writes to job-specific log file.

    Creates runs/<job_id>/run.log and writes structured logs there.
    """

    def __init__(self, job_id: str, runs_dir: Optional[str] = None):
        """
        Initialize job logger.

        Args:
            job_id: Job identifier.
            runs_dir: Base directory for runs. If None, uses absolute path from paths module.
        """
        from api.core.paths import RUNS_DIR
        
        self.job_id = job_id
        # Use absolute path from paths module if runs_dir not provided
        if runs_dir is None:
            runs_dir = str(RUNS_DIR)
        
        # Ensure runs_dir is absolute
        runs_dir_path = Path(runs_dir).resolve()
        self.log_file = runs_dir_path / job_id / "run.log"
        self.logger = None
        self._setup_logger()

    def _setup_logger(self) -> None:
        """Set up logger with file handler."""
        # Create job directory if needed
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Create logger with job-specific name
        logger_name = f"job.{self.job_id}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)

        # Remove existing handlers to avoid duplicates
        self.logger.handlers.clear()

        # Create file handler (use string path for FileHandler)
        file_handler = logging.FileHandler(str(self.log_file), encoding="utf-8")
        file_handler.setLevel(logging.INFO)

        # Set formatter
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)

        # Add handler
        self.logger.addHandler(file_handler)

        # Prevent propagation to root logger
        self.logger.propagate = False

    def info(self, message: str) -> None:
        """Log info message."""
        if self.logger:
            self.logger.info(message)

    def error(self, message: str) -> None:
        """Log error message."""
        if self.logger:
            self.logger.error(message)

    def warning(self, message: str) -> None:
        """Log warning message."""
        if self.logger:
            self.logger.warning(message)

    def debug(self, message: str) -> None:
        """Log debug message."""
        if self.logger:
            self.logger.debug(message)

    def log_status_change(self, old_status: str, new_status: str) -> None:
        """Log job status change."""
        self.info(f"Status change: {old_status} -> {new_status}")

    def log_artifact_registered(self, artifact_name: str, artifact_path: str) -> None:
        """Log artifact registration."""
        self.info(f"Artifact registered: {artifact_name} at {artifact_path}")

    def log_pipeline_start(self, question: str, log_path: Optional[str], model: str, mode: str) -> None:
        """Log pipeline execution start."""
        self.info(f"Pipeline started: question='{question}' log_path={log_path} model={model} mode={mode}")

    def log_step_start(self, step: str, progress_pct: int) -> None:
        """Log step start with progress."""
        self.info(f"Step started: {step} (progress: {progress_pct}%)")

    def log_step_complete(self, step: str, progress_pct: int) -> None:
        """Log step completion with progress."""
        self.info(f"Step completed: {step} (progress: {progress_pct}%)")

    def log_pipeline_complete(self, status: str, duration_ms: Optional[float] = None) -> None:
        """Log pipeline completion."""
        if duration_ms:
            self.info(f"Pipeline completed: status={status} duration={duration_ms:.2f}ms")
        else:
            self.info(f"Pipeline completed: status={status}")

    def log_error(self, error_message: str, traceback: Optional[str] = None) -> None:
        """Log error with optional traceback."""
        self.error(f"Error: {error_message}")
        if traceback:
            # Log traceback in chunks to avoid huge log entries
            lines = traceback.split("\n")
            for line in lines[:50]:  # Limit to first 50 lines
                self.error(f"  {line}")
            if len(lines) > 50:
                self.error(f"  ... ({len(lines) - 50} more lines)")
