"""
Job runner service for FastAPI.

Provides background job execution with status tracking via JobStore.
"""

from __future__ import annotations

import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any

from agent.runtime.job_models import JobRequest
from agent.runtime.worker import run_job
from api.config import get_runs_dir, settings
from api.core.paths import get_job_artifacts_dir, get_job_output_dir, get_job_run_dir
from api.schemas.job import JobArtifact, JobStatus, UpdateJobRequest
from api.services.job_store import JobStore
from api.utils.logging import JobLogger


class JobRunner:
    """
    Service for running log analysis jobs in the background.

    Manages job status transitions and artifact registration.
    """

    def __init__(self, job_store: Optional[JobStore] = None):
        """
        Initialize job runner.

        Args:
            job_store: JobStore instance. If None, creates a new one.
        """
        self.job_store = job_store or JobStore()
        self.runs_dir = self.job_store.runs_base_dir

    def _update_progress(
        self,
        job_id: str,
        step: str,
        progress_pct: int,
        job_logger: JobLogger,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        """
        Update job progress for a specific step.

        Args:
            job_id: Job identifier.
            step: Current step name.
            progress_pct: Progress percentage (0-100).
            job_logger: JobLogger instance.
            timeout_seconds: Optional timeout for this step.
        """
        step_started_at = datetime.now()
        self.job_store.update_job(
            job_id,
            UpdateJobRequest(
                current_step=step,
                progress_pct=progress_pct,
                step_started_at=step_started_at,
                step_timeout_seconds=timeout_seconds,
            ),
        )
        if timeout_seconds:
            job_logger.info(
                f"[{job_id}] Step: {step} | Progress: {progress_pct}% | "
                f"Started at {step_started_at.isoformat()} | Timeout: {timeout_seconds}s"
            )
        else:
            job_logger.info(f"[{job_id}] Step: {step} | Progress: {progress_pct}%")

    def run_job_background(
        self,
        job_id: str,
        question: str,
        input_log_path: Optional[str],
        model: str,
        mode: str = "rag",
    ) -> None:
        """
        Run a job in the background (for BackgroundTasks).

        Updates JobStore status: queued -> running -> succeeded/failed
        Tracks progress at each step: validate_input -> retrieve_context -> investigate -> generate_report -> write_artifacts
        Calls existing pipeline (run_job) and registers artifacts.

        Args:
            job_id: Job identifier from JobStore.
            question: User's question/query.
            input_log_path: Path to log file (optional).
            model: Ollama model name.
            mode: Execution mode ("heuristic" or "rag"). "rag" runs full RAG pipeline with artifacts, "heuristic" uses rule-based planning without RAG agents.
        """
        # Initialize job-specific logger (uses absolute paths from paths module)
        job_logger = JobLogger(job_id)
        job_logger.info(f"[{job_id}] Job started")

        pipeline_start_time = time.time()
        pipeline_max_runtime_sec = settings.pipeline_max_runtime_sec

        def _check_timeout() -> None:
            """Check if pipeline has exceeded max runtime and raise exception if so."""
            elapsed = time.time() - pipeline_start_time
            if elapsed > pipeline_max_runtime_sec:
                raise TimeoutError(
                    f"Pipeline exceeded maximum runtime of {pipeline_max_runtime_sec}s (elapsed: {elapsed:.1f}s)"
                )

        def _check_cancellation() -> None:
            """Check if cancellation was requested and raise exception if so."""
            if self.job_store.is_cancellation_requested(job_id):
                raise RuntimeError("Job cancellation was requested")

        try:
            # Step 1: Validate Input (0-10%)
            self._update_progress(job_id, "validate_input", 0, job_logger, timeout_seconds=None)
            job_logger.info(f"[{job_id}] Step: validate_input | Validating input parameters")

            # Validate log file exists if provided
            if input_log_path and not os.path.isfile(input_log_path):
                raise FileNotFoundError(f"Log file not found: {input_log_path}")

            self._update_progress(job_id, "validate_input", 10, job_logger)

            # Check for cancellation before starting pipeline
            _check_cancellation()

            # Update status to running
            old_status = "queued"
            self.job_store.update_job(
                job_id,
                UpdateJobRequest(
                    status="running",
                    started_at=datetime.now(),
                ),
            )
            job_logger.log_status_change(old_status, "running")

            # Get absolute paths for job directories
            job_output_dir = get_job_output_dir(job_id)
            job_artifacts_dir = get_job_artifacts_dir(job_id)
            job_run_dir = get_job_run_dir(job_id)

            # Log directory paths
            job_logger.info(f"[{job_id}] Job directories:")
            job_logger.info(f"[{job_id}]   Output: {job_output_dir}")
            job_logger.info(f"[{job_id}]   Artifacts: {job_artifacts_dir}")
            job_logger.info(f"[{job_id}]   Run: {job_run_dir}")

            # Log pipeline start
            job_logger.log_pipeline_start(question, input_log_path, model, mode)
            job_logger.info(f"[{job_id}] Pipeline started: question='{question}' log_path={input_log_path} model={model} mode={mode}")

            # Step 2: Retrieve Context (10-40%) - Timeout: 60s
            RETRIEVAL_TIMEOUT = 60
            self._update_progress(job_id, "retrieve_context", 10, job_logger, timeout_seconds=RETRIEVAL_TIMEOUT)
            job_logger.info(f"[{job_id}] Step: retrieve_context | Starting retrieval agent (timeout: {RETRIEVAL_TIMEOUT}s)")

            # Build JobRequest for existing pipeline
            job_request = JobRequest(
                query=question,
                file_paths=[input_log_path] if input_log_path else [],
            )

            # Temporarily monkey-patch create_job_dir to use our absolute job output directory
            from agent.runtime import storage
            original_create_job_dir = storage.create_job_dir

            def patched_create_job_dir(base: str = "output/jobs"):
                """Return our job_id and absolute output directory."""
                return job_id, str(job_output_dir)

            storage.create_job_dir = patched_create_job_dir

            try:
                # Check timeout and cancellation before starting pipeline
                _check_timeout()
                _check_cancellation()
                
                # Import step functions from worker
                from agent.runtime.worker import (
                    run_retrieval_step,
                    run_investigation_step,
                    run_reporter_step,
                )
                
                # Mode-specific step execution
                if mode == "rag":
                    # RAG mode: Execute each step individually with its own timeout
                    retrieval_results = None
                    investigation_findings = None
                    
                    # Step 1: Retrieval (10-40%) - Timeout: 60s
                    step_start_time = time.time()
                    job_logger.info(f"[{job_id}] Step started: retrieve_context timeout={RETRIEVAL_TIMEOUT}s")
                    
                    def execute_retrieval():
                        return run_retrieval_step(job_request, str(job_output_dir), job_id)
                    
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(execute_retrieval)
                        try:
                            retrieval_path_str = future.result(timeout=RETRIEVAL_TIMEOUT)
                        except FutureTimeoutError:
                            step_duration_ms = int((time.time() - step_start_time) * 1000)
                            job_logger.error(f"[{job_id}] Step timed out: retrieve_context duration_ms={step_duration_ms}")
                            raise TimeoutError(
                                f"Timeout in step 'retrieve_context' after {RETRIEVAL_TIMEOUT}s"
                            )
                    
                    step_duration_ms = int((time.time() - step_start_time) * 1000)
                    job_logger.info(f"[{job_id}] Step completed: retrieve_context duration_ms={step_duration_ms}")
                    
                    # Copy and register retrieval.json immediately
                    if retrieval_path_str and os.path.isfile(retrieval_path_str):
                        retrieval_path = Path(retrieval_path_str)
                        artifact_path = self._copy_artifact_to_artifacts_dir(
                            job_id, str(retrieval_path), "retrieval.json", job_artifacts_dir, job_logger
                        )
                        self._register_artifact(job_id, "retrieval.json", artifact_path, "application/json", job_logger)
                        self._update_progress(job_id, "retrieve_context", 40, job_logger)
                        job_logger.info(f"[{job_id}] Step: retrieve_context | Completed - retrieval.json created and registered")
                        
                        # Load retrieval results for next step
                        import json
                        with open(retrieval_path, "r", encoding="utf-8") as f:
                            retrieval_results = json.load(f)
                    else:
                        self._update_progress(job_id, "retrieve_context", 30, job_logger)
                        job_logger.warning(f"[{job_id}] Step: retrieve_context | No retrieval.json produced")
                    
                    # Check cancellation before investigation step
                    _check_cancellation()
                    
                    # Step 2: Investigation (40-70%) - Timeout: 180s
                    INVESTIGATION_TIMEOUT = 180
                    self._update_progress(job_id, "investigate", 40, job_logger, timeout_seconds=INVESTIGATION_TIMEOUT)
                    step_start_time = time.time()
                    job_logger.info(f"[{job_id}] Step started: investigate timeout={INVESTIGATION_TIMEOUT}s")
                    
                    def execute_investigation():
                        return run_investigation_step(job_request, retrieval_results, str(job_output_dir), job_id)
                    
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(execute_investigation)
                        try:
                            findings_path_str = future.result(timeout=INVESTIGATION_TIMEOUT)
                        except FutureTimeoutError:
                            step_duration_ms = int((time.time() - step_start_time) * 1000)
                            job_logger.error(f"[{job_id}] Step timed out: investigate duration_ms={step_duration_ms}")
                            raise TimeoutError(
                                f"Timeout in step 'investigate' after {INVESTIGATION_TIMEOUT}s"
                            )
                    
                    step_duration_ms = int((time.time() - step_start_time) * 1000)
                    job_logger.info(f"[{job_id}] Step completed: investigate duration_ms={step_duration_ms}")
                    
                    # Copy and register findings.json immediately
                    if findings_path_str and os.path.isfile(findings_path_str):
                        findings_path = Path(findings_path_str)
                        artifact_path = self._copy_artifact_to_artifacts_dir(
                            job_id, str(findings_path), "findings.json", job_artifacts_dir, job_logger
                        )
                        self._register_artifact(job_id, "findings.json", artifact_path, "application/json", job_logger)
                        self._update_progress(job_id, "investigate", 70, job_logger)
                        job_logger.info(f"[{job_id}] Step: investigate | Completed - findings.json created and registered")
                        
                        # Load investigation findings for next step
                        import json
                        with open(findings_path, "r", encoding="utf-8") as f:
                            investigation_findings = json.load(f)
                    else:
                        self._update_progress(job_id, "investigate", 60, job_logger)
                        job_logger.warning(f"[{job_id}] Step: investigate | No findings.json produced")
                    
                    # Check cancellation before report generation step
                    _check_cancellation()
                    
                    # Step 3: Generate Report (70-90%) - Timeout: 180s
                    REPORT_TIMEOUT = 180
                    self._update_progress(job_id, "generate_report", 70, job_logger, timeout_seconds=REPORT_TIMEOUT)
                    step_start_time = time.time()
                    job_logger.info(f"[{job_id}] Step started: generate_report timeout={REPORT_TIMEOUT}s")
                    
                    def execute_reporter():
                        return run_reporter_step(job_request, retrieval_results, investigation_findings, str(job_output_dir), job_id)
                    
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(execute_reporter)
                        try:
                            report_path_str = future.result(timeout=REPORT_TIMEOUT)
                        except FutureTimeoutError:
                            step_duration_ms = int((time.time() - step_start_time) * 1000)
                            job_logger.error(f"[{job_id}] Step timed out: generate_report duration_ms={step_duration_ms}")
                            raise TimeoutError(
                                f"Timeout in step 'generate_report' after {REPORT_TIMEOUT}s"
                            )
                    
                    step_duration_ms = int((time.time() - step_start_time) * 1000)
                    job_logger.info(f"[{job_id}] Step completed: generate_report duration_ms={step_duration_ms}")
                    
                    # Copy and register final_answer.md immediately
                    if report_path_str and os.path.isfile(report_path_str):
                        report_path = Path(report_path_str)
                        artifact_path = self._copy_artifact_to_artifacts_dir(
                            job_id, str(report_path), "final_answer.md", job_artifacts_dir, job_logger
                        )
                        self._register_artifact(job_id, "final_answer.md", artifact_path, "text/markdown", job_logger)
                        self._update_progress(job_id, "generate_report", 90, job_logger)
                        job_logger.info(f"[{job_id}] Step: generate_report | Completed - final_answer.md created and registered")
                    else:
                        self._update_progress(job_id, "generate_report", 85, job_logger)
                        job_logger.warning(f"[{job_id}] Step: generate_report | No final_answer.md produced")
                    
                    # Create a minimal job_result for compatibility
                    from agent.runtime.job_models import JobResult, RunTiming
                    job_result = JobResult(
                        job_id=job_id,
                        status=JobStatus.SUCCEEDED.value,  # Use .value to get string
                        final_answer="Report generated successfully",
                        tool_calls=[],
                        tool_results=[],
                        artifacts=[],
                        warnings=[],
                        errors=[],
                        timing=RunTiming(started_at=datetime.fromtimestamp(pipeline_start_time), finished_at=datetime.now()),
                    )
                else:
                    # Heuristic mode: Skip RAG steps, generate report from tool results
                    # Run tool execution pipeline (without RAG agents)
                    job_logger.info(f"[{job_id}] Step: generate_report | Heuristic mode - running tool execution pipeline")
                    REPORT_TIMEOUT = 180
                    self._update_progress(job_id, "generate_report", 70, job_logger, timeout_seconds=REPORT_TIMEOUT)
                    step_start_time = time.time()
                    job_logger.info(f"[{job_id}] Step started: generate_report timeout={REPORT_TIMEOUT}s")
                    
                    def execute_heuristic_pipeline():
                        return run_job(job_request, mode=mode)
                    
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(execute_heuristic_pipeline)
                        try:
                            job_result = future.result(timeout=REPORT_TIMEOUT)
                        except FutureTimeoutError:
                            step_duration_ms = int((time.time() - step_start_time) * 1000)
                            job_logger.error(f"[{job_id}] Step timed out: generate_report duration_ms={step_duration_ms}")
                            raise TimeoutError(
                                f"Timeout in step 'generate_report' after {REPORT_TIMEOUT}s"
                            )
                    
                    step_duration_ms = int((time.time() - step_start_time) * 1000)
                    job_logger.info(f"[{job_id}] Step completed: generate_report duration_ms={step_duration_ms}")
                    
                    # Copy and register final_answer.md if it exists
                    report_path = job_output_dir / "final_answer.md"
                    if report_path.is_file():
                        artifact_path = self._copy_artifact_to_artifacts_dir(
                            job_id, str(report_path), "final_answer.md", job_artifacts_dir, job_logger
                        )
                        self._register_artifact(job_id, "final_answer.md", artifact_path, "text/markdown", job_logger)
                        self._update_progress(job_id, "generate_report", 90, job_logger)
                        job_logger.info(f"[{job_id}] Step: generate_report | Completed - final_answer.md created and registered")
                    else:
                        self._update_progress(job_id, "generate_report", 85, job_logger)
                        job_logger.warning(f"[{job_id}] Step: generate_report | No final_answer.md found at {report_path}")

            finally:
                # Restore original function
                storage.create_job_dir = original_create_job_dir

            # Check cancellation before final artifact writing
            _check_cancellation()

            # Step 5: Write Artifacts (90-100%)
            self._update_progress(job_id, "write_artifacts", 90, job_logger)
            job_logger.info(f"[{job_id}] Step: write_artifacts | Writing job.json and finalizing artifacts")
            
            # Write job.json metadata to artifacts directory
            self._write_job_metadata(job_id, job_artifacts_dir, job_logger)

            # Defensive check: verify expected artifacts exist based on mode
            if mode == "rag":
                # RAG mode: require retrieval.json, findings.json, final_answer.md
                expected_artifacts = ["retrieval.json", "findings.json", "final_answer.md", "job.json"]
                critical_artifacts = ["retrieval.json", "findings.json", "final_answer.md"]
            else:
                # Heuristic mode: only require final_answer.md
                expected_artifacts = ["final_answer.md", "job.json"]
                critical_artifacts = ["final_answer.md"]
            
            missing_artifacts = []
            for artifact_name in expected_artifacts:
                artifact_path = job_artifacts_dir / artifact_name
                if not artifact_path.is_file():
                    missing_artifacts.append(artifact_name)
                    job_logger.warning(f"[{job_id}] Missing expected artifact: {artifact_name} at {artifact_path}")

            if missing_artifacts:
                error_msg = f"Missing required artifacts: {', '.join(missing_artifacts)}"
                job_logger.error(f"[{job_id}] {error_msg}")
                # Mark job as failed if critical artifacts are missing
                if any(artifact in missing_artifacts for artifact in critical_artifacts):
                    raise RuntimeError(error_msg)

            self._update_progress(job_id, "write_artifacts", 100, job_logger)
            job_logger.info(f"[{job_id}] Step: write_artifacts | Completed - all artifacts written and registered")

            # Calculate pipeline duration
            pipeline_duration_ms = int((time.time() - pipeline_start_time) * 1000)

            # Determine final status
            final_status = JobStatus.SUCCEEDED.value if job_result.status in ("succeeded", "succeeded_with_errors") else JobStatus.FAILED.value

            # Log pipeline completion
            job_logger.log_pipeline_complete(final_status, pipeline_duration_ms)

            # Update job with completion status
            self.job_store.update_job(
                job_id,
                UpdateJobRequest(
                    status=final_status,
                    finished_at=datetime.now(),
                    current_step=None,  # Clear current step when done
                    progress_pct=100,
                    step_started_at=None,  # Clear step timing when done
                    step_timeout_seconds=None,
                    duration_ms=pipeline_duration_ms,
                ),
            )
            job_logger.log_status_change("running", final_status)
            job_logger.info(f"[{job_id}] Job completed: status={final_status} duration={pipeline_duration_ms}ms")

        except TimeoutError as exc:
            # Pipeline exceeded max runtime
            error_message = str(exc)
            elapsed_sec = time.time() - pipeline_start_time
            
            job_logger.error(f"[{job_id}] Pipeline timeout: {error_message}")
            job_logger.error(f"[{job_id}] Elapsed time: {elapsed_sec:.1f}s, Max allowed: {pipeline_max_runtime_sec}s")

            # Calculate pipeline duration
            pipeline_duration_ms = int(elapsed_sec * 1000)

            # Get current step for better error message
            job_record = self.job_store.get_job(job_id)
            current_step = job_record.current_step if job_record else None
            step_timeout = job_record.step_timeout_seconds if job_record else None
            
            # Write job.json to artifacts even on timeout
            try:
                self._write_job_metadata(job_id, job_artifacts_dir, job_logger)
            except Exception as write_exc:
                job_logger.warning(f"[{job_id}] Failed to write job.json on timeout: {write_exc}")
            
            # Update job with timeout error
            self.job_store.update_job(
                job_id,
                UpdateJobRequest(
                    status=JobStatus.FAILED.value,
                    finished_at=datetime.now(),
                    error=f"Timeout in step '{current_step or 'unknown'}' after {step_timeout or 'unknown'}s: {error_message}",
                    current_step=None,  # Clear current step on failure
                    step_started_at=None,
                    step_timeout_seconds=None,
                    duration_ms=pipeline_duration_ms,
                ),
            )
            job_logger.log_status_change("running", "failed")
            job_logger.error(f"[{job_id}] Job failed due to timeout")

        except RuntimeError as exc:
            # Check if this is a cancellation request
            if "cancellation was requested" in str(exc):
                # Handle cancellation gracefully
                elapsed_sec = time.time() - pipeline_start_time
                pipeline_duration_ms = int(elapsed_sec * 1000)

                job_logger.info(f"[{job_id}] Job cancellation requested - aborting gracefully")
                job_logger.info(f"[{job_id}] Elapsed time: {elapsed_sec:.1f}s")

                # Update job with cancelled status
                self.job_store.update_job(
                    job_id,
                    UpdateJobRequest(
                        status=JobStatus.CANCELLED.value,
                        finished_at=datetime.now(),
                        current_step=None,
                        step_started_at=None,
                        step_timeout_seconds=None,
                        duration_ms=pipeline_duration_ms,
                    ),
                )
                job_logger.log_status_change("running", "cancelled")

                # Write job.json metadata even on cancellation
                job_artifacts_dir = get_job_artifacts_dir(job_id)
                if job_artifacts_dir.is_dir():
                    self._write_job_metadata(job_id, job_artifacts_dir, job_logger)

                job_logger.info(f"[{job_id}] Job cancelled successfully")
                return  # Exit gracefully without re-raising

            # Re-raise if it's not a cancellation
            raise

        except Exception as exc:
            # Capture exception details
            error_message = str(exc)
            error_traceback = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            # Store first 1000 chars of traceback to avoid huge error fields
            error_traceback_snippet = error_traceback[:1000]

            # Log error
            job_logger.log_error(error_message, error_traceback)

            # Calculate pipeline duration
            pipeline_duration_ms = int((time.time() - pipeline_start_time) * 1000)

            # Update job with error
            self.job_store.update_job(
                job_id,
                UpdateJobRequest(
                    status=JobStatus.FAILED.value,
                    finished_at=datetime.now(),
                    error=f"{error_message}\n\nTraceback:\n{error_traceback_snippet}",
                    current_step=None,  # Clear current step on failure
                    duration_ms=pipeline_duration_ms,
                ),
            )
            job_logger.log_status_change("running", "failed")
            job_logger.error(f"[{job_id}] Job failed: error={error_message}")

    def _copy_artifact_to_artifacts_dir(
        self,
        job_id: str,
        source_path: str,
        artifact_name: str,
        artifacts_dir: Path,
        job_logger: Optional[JobLogger] = None,
    ) -> str:
        """
        Copy artifact from pipeline output to artifacts directory.

        Args:
            job_id: Job identifier.
            source_path: Source file path in pipeline output directory.
            artifact_name: Name of the artifact file.
            artifacts_dir: Target artifacts directory (Path object).
            job_logger: Optional JobLogger instance for logging.

        Returns:
            Absolute path to the copied artifact file as string.
        """
        import shutil

        # Ensure artifacts directory exists
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = artifacts_dir / artifact_name
        source_path_obj = Path(source_path)
        
        if not source_path_obj.is_file():
            if job_logger:
                job_logger.error(f"[{job_id}] Source artifact not found: {source_path}")
            raise FileNotFoundError(f"Source artifact not found: {source_path}")
        
        shutil.copy2(source_path_obj, target_path)
        
        # Verify file was copied and log size
        if target_path.is_file():
            size_bytes = target_path.stat().st_size
            if job_logger:
                job_logger.info(
                    f"[{job_id}] Wrote {artifact_name} size={size_bytes} bytes to {target_path}"
                )
        else:
            if job_logger:
                job_logger.error(f"[{job_id}] Failed to copy {artifact_name} to {target_path}")
            raise RuntimeError(f"Failed to copy {artifact_name} to {target_path}")
        
        return str(target_path)

    def _register_artifact(
        self,
        job_id: str,
        artifact_name: str,
        artifact_path: str,
        content_type: str,
        job_logger: Optional[JobLogger] = None,
    ) -> None:
        """
        Register an artifact in JobStore immediately after writing.

        Args:
            job_id: Job identifier.
            artifact_name: Name of the artifact.
            artifact_path: Full path to the artifact file.
            content_type: MIME type of the artifact.
            job_logger: Optional JobLogger instance for logging.
        """
        # Ensure file exists before registering
        if not os.path.isfile(artifact_path):
            if job_logger:
                job_logger.warning(f"[{job_id}] Artifact file does not exist: {artifact_path}")
            return

        # Use relative path from repo root for portability
        relative_path = os.path.relpath(artifact_path, os.getcwd())
        
        # Register artifact in JobStore
        updated_record = self.job_store.add_artifact(
            job_id=job_id,
            name=artifact_name,
            path=relative_path,
            content_type=content_type,
        )
        
        if updated_record:
            if job_logger:
                # Get file size for logging
                try:
                    size_bytes = os.path.getsize(artifact_path)
                    job_logger.info(
                        f"[{job_id}] Registered artifact: {artifact_name} "
                        f"path={relative_path} size={size_bytes} bytes"
                    )
                except OSError:
                    job_logger.log_artifact_registered(artifact_name, relative_path)
        else:
            if job_logger:
                job_logger.error(f"[{job_id}] Failed to register artifact: {artifact_name}")

    def _write_job_metadata(
        self,
        job_id: str,
        artifacts_dir: Path,
        job_logger: Optional[JobLogger] = None,
    ) -> None:
        """
        Write job.json metadata file to artifacts directory.

        Args:
            job_id: Job identifier.
            artifacts_dir: Artifacts directory (artifacts/<job_id>/).
            job_logger: Optional JobLogger instance for logging.
        """
        import json

        # Get current job record
        job_record = self.job_store.get_job(job_id)
        if not job_record:
            if job_logger:
                job_logger.warning(f"[{job_id}] Cannot write job.json: job record not found")
            return

        # Prepare job metadata
        job_metadata = {
            "job_id": job_record.job_id,
            "status": job_record.status,
            "created_at": job_record.created_at.isoformat() if job_record.created_at else None,
            "started_at": job_record.started_at.isoformat() if job_record.started_at else None,
            "finished_at": job_record.finished_at.isoformat() if job_record.finished_at else None,
            "question": job_record.question,
            "input_log_path": job_record.input_log_path,
            "model": job_record.model,
            "error": job_record.error,
            "current_step": job_record.current_step,
            "progress_pct": job_record.progress_pct,
            "step_started_at": job_record.step_started_at.isoformat() if job_record.step_started_at else None,
            "step_timeout_seconds": job_record.step_timeout_seconds,
            "duration_ms": job_record.duration_ms,
            "artifacts": [
                {
                    "name": artifact.name,
                    "path": artifact.path,
                    "content_type": artifact.content_type,
                }
                for artifact in job_record.artifacts
            ],
        }

        # Write job.json to artifacts directory
        job_json_path = artifacts_dir / "job.json"
        with open(job_json_path, "w", encoding="utf-8") as f:
            json.dump(job_metadata, f, indent=2, ensure_ascii=False)

        # Verify file was written and log size
        if job_json_path.is_file():
            size_bytes = job_json_path.stat().st_size
            if job_logger:
                job_logger.info(
                    f"[{job_id}] Wrote job.json size={size_bytes} bytes to {job_json_path}"
                )
        else:
            if job_logger:
                job_logger.error(f"[{job_id}] Failed to write job.json to {job_json_path}")
            raise RuntimeError(f"Failed to write job.json to {job_json_path}")

        # Register job.json as an artifact
        self._register_artifact(
            job_id, "job.json", str(job_json_path), "application/json", job_logger
        )