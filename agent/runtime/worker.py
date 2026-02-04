"""
Worker Module

Main worker that executes log analysis jobs.
Orchestrates planning, tool execution, and result compilation.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List

from agent.runtime.job_models import (
    JobRequest,
    JobResult,
    JobStatus,
    ToolCall,
    ArtifactRef,
    RunTiming,
)
from agent.runtime.planner import plan_steps
from agent.runtime.tool_executor import ToolExecutor
from agent.runtime.storage import (
    create_job_dir,
    write_job_state,
    artifact_ref_from_path,
    create_job_context,
    copy_input_files,
    write_tool_result,
)
from agent.runtime.job_models import JobContext

try:
    from agent.llm.llama_client import LLaMAClient
except ImportError:
    LLaMAClient = None


def run_job(request: JobRequest, mode: str = "heuristic") -> JobResult:
    """
    Execute a log analysis job.

    Steps:
        1. Create job_id + job_dir
        2. Call plan_steps to determine tool calls
        3. Execute each tool call via ToolExecutor
        4. Build final answer (combine summaries or use LLM)
        5. Return JobResult

    Args:
        request: JobRequest containing query and file paths.
        mode: Planning mode - "heuristic" or "llm". Default: "heuristic".

    Returns:
        JobResult with all tool results, artifacts, and final answer.
    """
    timing = RunTiming(started_at=datetime.now())

    job_id, job_dir = create_job_dir()

    # Initialize collections before any operations that might fail
    tool_calls: List[ToolCall] = []
    tool_results: List[Dict[str, Any]] = []
    artifacts: List[ArtifactRef] = []
    warnings: List[str] = []
    errors: List[str] = []

    # Create job context with directory structure
    context = create_job_context(job_id, job_dir)

    # Copy input files to job directory
    if request.file_paths:
        try:
            context = copy_input_files(context, request.file_paths)
        except Exception as exc:
            # If file copying fails, still create context but log error
            errors.append(f"Failed to copy input files: {exc}")

    initial_state = {
        "job_id": job_id,
        "status": "running",
        "query": request.query,
        "file_paths": request.file_paths,
        "mode": mode,
        "job_context": {
            "job_dir": context.job_dir,
            "artifacts_dir": context.artifacts_dir,
            "inputs_dir": context.inputs_dir,
            "input_files": context.input_files,
        },
    }
    write_job_state(job_dir, initial_state)

    tool_executor = ToolExecutor()

    try:
        # Update request with job-scoped file paths for planning
        planning_request = request
        if context.input_files:
            # Use copied file paths for planning
            planning_file_paths = [
                context.input_files.get(orig_path, orig_path)
                for orig_path in request.file_paths
            ]
            # Create a modified request with job-scoped paths
            planning_request = JobRequest(
                query=request.query,
                file_paths=planning_file_paths,
                options=request.options,
            )

        planned_calls = plan_steps(planning_request, mode=mode)

        for tool_index, tool_call in enumerate(planned_calls):
            tool_call.started_at = datetime.now()
            tool_call.status = "running"

            try:
                result = tool_executor.execute(tool_call.name, tool_call.arguments, ctx=context)

                tool_call.finished_at = datetime.now()
                tool_call.status = "success" if result.get("status") == "success" else "error"

                tool_results.append(result)

                # Persist tool result to individual JSON file (never crash on IO errors)
                tool_result_path = write_tool_result(
                    job_dir, tool_index, tool_call.name, result
                )
                if tool_result_path is None:
                    warnings.append(
                        f"Failed to persist tool result for '{tool_call.name}' "
                        f"(index {tool_index})"
                    )

                if result.get("status") == "success":
                    result_artifacts = result.get("artifacts", [])
                    for artifact_dict in result_artifacts:
                        artifact_ref = artifact_ref_from_path(
                            path=artifact_dict.get("path", ""),
                            from_tool=tool_call.name,
                            description=artifact_dict.get("name", ""),
                        )
                        artifacts.append(artifact_ref)

                    summary = result.get("summary", {})
                    tool_call.summary = summary.get("headline", "Tool executed successfully")
                else:
                    result_errors = result.get("errors", [])
                    if result_errors:
                        errors.extend([str(e) for e in result_errors])

                result_warnings = result.get("warnings", [])
                if result_warnings:
                    warnings.extend([w.get("message", str(w)) if isinstance(w, dict) else str(w) for w in result_warnings])

            except Exception as exc:
                tool_call.finished_at = datetime.now()
                tool_call.status = "error"
                tool_call.summary = f"Tool execution failed: {exc}"
                errors.append(f"Tool '{tool_call.name}' failed: {exc}")

            tool_calls.append(tool_call)

        final_answer = _build_final_answer(request, tool_results, artifacts, mode)

        timing.finished_at = datetime.now()
        if timing.started_at and timing.finished_at:
            delta = timing.finished_at - timing.started_at
            timing.duration_ms = int(delta.total_seconds() * 1000)

        status: JobStatus = "succeeded" if not errors else "failed"

        job_result = JobResult(
            job_id=job_id,
            status=status,
            final_answer=final_answer,
            tool_calls=tool_calls,
            tool_results=tool_results,
            artifacts=artifacts,
            warnings=warnings,
            errors=errors,
            timing=timing,
        )

        write_job_state(job_dir, job_result.model_dump())

        return job_result

    except Exception as exc:
        timing.finished_at = datetime.now()
        if timing.started_at and timing.finished_at:
            delta = timing.finished_at - timing.started_at
            timing.duration_ms = int(delta.total_seconds() * 1000)

        job_result = JobResult(
            job_id=job_id,
            status="failed",
            final_answer=None,
            tool_calls=tool_calls,
            tool_results=tool_results,
            artifacts=artifacts,
            warnings=warnings,
            errors=[str(exc)],
            timing=timing,
        )

        write_job_state(job_dir, job_result.model_dump())

        return job_result


def _build_final_answer(
    request: JobRequest,
    tool_results: List[Dict[str, Any]],
    artifacts: List[ArtifactRef],
    mode: str,
) -> str:
    """
    Build the final answer from tool results.

    If LLM is available and mode is "llm", use LLM to compose answer.
    Otherwise, combine tool summaries and artifact paths.
    """
    if mode == "llm" and LLaMAClient is not None:
        try:
            return _build_final_answer_llm(request, tool_results, artifacts)
        except Exception:
            pass

    return _build_final_answer_heuristic(tool_results, artifacts)


def _build_final_answer_heuristic(
    tool_results: List[Dict[str, Any]],
    artifacts: List[ArtifactRef],
) -> str:
    """Build final answer by combining tool summaries."""
    parts: List[str] = []

    for result in tool_results:
        if result.get("status") == "success":
            summary = result.get("summary", {})
            headline = summary.get("headline", "Tool executed")
            parts.append(f"• {headline}")

    if artifacts:
        parts.append("\nGenerated artifacts:")
        for artifact in artifacts:
            parts.append(f"  - {artifact.name}: {artifact.path}")

    if not parts:
        return "Job completed, but no results were generated."

    return "\n".join(parts)


def _build_final_answer_llm(
    request: JobRequest,
    tool_results: List[Dict[str, Any]],
    artifacts: List[ArtifactRef],
) -> str:
    """
    Build final answer using LLM to compose a natural language response.

    Important: LLM only narrates/composes the answer from tool results.
    All computation, analysis, and truth comes from the tools - LLM just formats it.
    """
    if LLaMAClient is None:
        return _build_final_answer_heuristic(tool_results, artifacts)

    summaries = []
    for result in tool_results:
        if result.get("status") == "success":
            summary = result.get("summary", {})
            headline = summary.get("headline", "")
            key_metrics = summary.get("key_metrics", {})
            if headline:
                summaries.append(f"{headline} (Metrics: {key_metrics})")

    artifact_list = [f"{a.name} at {a.path}" for a in artifacts]

    prompt = f"""You are a log analysis narrator. Your role is to compose a natural language answer from tool results.

User query: {request.query}

Tool results (already computed by tools):
{chr(10).join(summaries) if summaries else "No successful tool results."}

Generated artifacts:
{chr(10).join(artifact_list) if artifact_list else "No artifacts generated."}

Your task: Compose a clear, concise natural language answer that addresses the user's query using the tool results above.

Rules:
- Use the tool results as facts (they contain the truth)
- Do NOT perform any computation, analysis, or filtering yourself
- Do NOT extract timestamps, error codes, or count frequencies - tools already did that
- Only narrate and format the information provided by tools
- Be concise and focus on key findings from the tool results

Provide your answer:"""

    try:
        client = LLaMAClient()
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=os.getenv("LLAMA_MODEL", "llama-3.1-8b"),
            temperature=0.7,
        )
        return response.strip()
    except Exception:
        return _build_final_answer_heuristic(tool_results, artifacts)
