"""
Tool Executor

Executes tools from the registry and validates their outputs.
Handles exceptions and ensures all outputs conform to ToolResult schema.
Enforces Step 6 rules: job-scoped paths, artifact validation, no path escapes.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from agent.runtime.tool_registry import get_tool
from agent.tool_wrapper import validate_tool_result
from agent.runtime.job_models import JobContext


class ToolExecutor:
    """
    Executes tools from the registry and validates their outputs.

    Enforces Step 6 rules:
    - All artifacts must be under output/jobs/<job_id>/
    - File paths are mapped to job-scoped copies
    - output_dir is always injected from JobContext
    - Path escapes are detected and converted to errors

    Usage:
        executor = ToolExecutor()
        result = executor.execute("run_log_summary", {"file_path": "data/sample.log"}, ctx=job_context)
    """

    def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: Optional[JobContext] = None,
    ) -> Dict[str, Any]:
        """
        Execute a tool by name with the given arguments.

        Steps:
            1. Map file_path to job-scoped path if ctx is available
            2. Inject output_dir from ctx (always override - job directory is law)
            3. Fetch function from TOOL_REGISTRY
            4. Call it safely
            5. Validate output using validate_tool_result
            6. Enforce artifact path validation (must be under job directory)
            7. On exception, return a ToolResult-shaped failure dict

        Args:
            tool_name: Name of the tool (e.g. "run_log_summary").
            args: Dictionary of keyword arguments to pass to the tool.
            ctx: Optional JobContext for job-scoped path enforcement.

        Returns:
            Validated ToolResult dictionary with enforced artifact paths.
        """
        # Prepare arguments with job context injection
        prepared_args = args.copy()

        # Map file_path to job-scoped path if ctx is available
        if ctx and "file_path" in prepared_args:
            original_path = prepared_args["file_path"]
            if original_path in ctx.input_files:
                prepared_args["file_path"] = ctx.input_files[original_path]

        # Inject output_dir from ctx (always override - job directory is law)
        if ctx:
            # Override any existing output_dir with job-scoped one
            prepared_args["output_dir"] = ctx.artifacts_dir

        # Construct basic input structure for error cases (use original args for display)
        file_path = args.get("file_path", "unknown")
        options = {k: v for k, v in args.items() if k != "file_path"}
        input_params = {
            "file_path": file_path,
            "options": options,
        }

        try:
            tool_func = get_tool(tool_name)
        except KeyError as exc:
            raw_failure = {
                "tool": tool_name,
                "status": "error",
                "input": input_params,
                "summary": {
                    "headline": f"Tool '{tool_name}' not found",
                    "key_metrics": {},
                },
                "data": {
                    "items": [],
                    "text": None,
                    "json": {},
                },
                "artifacts": [],
                "warnings": [],
                "errors": [str(exc)],
            }
            return validate_tool_result(raw_failure)

        try:
            raw_result = tool_func(**prepared_args)
            # Ensure the tool sets its own "tool" field; if not, inject it
            if isinstance(raw_result, dict):
                raw_result.setdefault("tool", tool_name)
                raw_result.setdefault("input", input_params)
            else:
                raw_result = {
                    "tool": tool_name,
                    "status": "error",
                    "input": input_params,
                    "summary": {
                        "headline": "Tool returned non-dict result",
                        "key_metrics": {},
                    },
                    "data": {
                        "items": [],
                        "text": None,
                        "json": {"raw_result_type": str(type(raw_result))},
                    },
                    "artifacts": [],
                    "warnings": [],
                    "errors": [
                        "Tool returned a non-dict result. Expected a ToolResult-like dict."
                    ],
                }

            # Validate and enforce artifact paths (Step 6 rule)
            validated_result = validate_tool_result(raw_result)
            validated_result = self._enforce_artifact_paths(validated_result, ctx)

            return validated_result

        except Exception as exc:
            # Worker must never crash - convert all exceptions to ToolResult errors
            raw_failure = {
                "tool": tool_name,
                "status": "error",
                "input": input_params,
                "summary": {
                    "headline": "Tool execution failed",
                    "key_metrics": {},
                },
                "data": {
                    "items": [],
                    "text": None,
                    "json": {"exception_type": type(exc).__name__},
                },
                "artifacts": [],
                "warnings": [],
                "errors": [f"{type(exc).__name__}: {str(exc)}"],
            }
            return validate_tool_result(raw_failure)

    def _enforce_artifact_paths(
        self, result: Dict[str, Any], ctx: Optional[JobContext]
    ) -> Dict[str, Any]:
        """
        Enforce Step 6 rule: all artifact paths must be under output/jobs/<job_id>/.

        If ctx is provided:
        - Rewrite artifact paths that escape the job directory
        - Convert paths outside job directory to errors
        - Ensure all paths are absolute or relative to job directory

        Args:
            result: Validated ToolResult dictionary.
            ctx: Optional JobContext for path validation.

        Returns:
            Result dictionary with enforced artifact paths.
        """
        if not ctx:
            # No context means no enforcement (backward compatibility)
            return result

        artifacts = result.get("artifacts", [])
        if not artifacts:
            return result

        job_dir_abs = os.path.abspath(ctx.job_dir)
        artifacts_dir_abs = os.path.abspath(ctx.artifacts_dir)
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])

        validated_artifacts = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue

            artifact_path = artifact.get("path", "")
            if not artifact_path:
                validated_artifacts.append(artifact)
                continue

            # Normalize path to absolute
            if os.path.isabs(artifact_path):
                artifact_abs = os.path.abspath(artifact_path)
            else:
                # Relative path - resolve relative to artifacts_dir
                artifact_abs = os.path.abspath(
                    os.path.join(artifacts_dir_abs, artifact_path)
                )

            # Check if path is under job directory
            # Normalize paths for comparison (handle trailing slashes)
            job_dir_normalized = os.path.normpath(job_dir_abs) + os.sep
            artifact_normalized = os.path.normpath(artifact_abs)

            # Check if artifact path starts with job directory path
            is_under_job_dir = artifact_normalized.startswith(job_dir_normalized) or (
                artifact_normalized == job_dir_abs
            )

            if not is_under_job_dir:
                # Path escape detected - convert to error
                error_msg = (
                    f"Artifact path '{artifact_path}' is outside job directory "
                    f"'{ctx.job_dir}'. Path escapes are not allowed."
                )
                errors.append(error_msg)
                warnings.append(
                    f"Skipped artifact '{artifact.get('name', 'unknown')}': {error_msg}"
                )
                continue

            # Rewrite path to be relative to artifacts_dir for consistency
            # Keep path as-is if already valid (preserves relative paths)
            try:
                artifact_rel = os.path.relpath(artifact_abs, artifacts_dir_abs)
                # If artifact is directly in artifacts_dir, use just the filename
                if artifact_rel == ".":
                    artifact_rel = os.path.basename(artifact_abs)
                # Use forward slashes for consistency (even on Windows)
                artifact_rel = artifact_rel.replace(os.sep, "/")
                # Construct path relative to artifacts_dir
                final_path = os.path.join(ctx.artifacts_dir, artifact_rel).replace(os.sep, "/")
            except ValueError:
                # If relpath fails (different drives on Windows), keep absolute path
                final_path = artifact_abs

            # Update artifact with validated path
            validated_artifact = artifact.copy()
            validated_artifact["path"] = final_path
            validated_artifacts.append(validated_artifact)

        # Update result with validated artifacts and any new errors/warnings
        result = result.copy()
        result["artifacts"] = validated_artifacts
        result["errors"] = errors
        result["warnings"] = warnings

        # If we had path escapes, mark as error status
        if errors and result.get("status") == "success":
            result["status"] = "error"

        return result
