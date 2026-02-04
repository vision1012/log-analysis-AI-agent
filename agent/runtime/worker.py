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
from agent.planner import create_plan
from agent.runtime.tool_executor import ToolExecutor
from agent.runtime.storage import (
    create_job_dir,
    write_job_state,
    read_job_state,
    update_job_state,
    get_job_status,
    check_artifact_exists,
    get_existing_artifacts,
    artifact_ref_from_path,
    create_job_context,
    copy_input_files,
    write_tool_result,
    write_plan,
)
from agent.runtime.job_models import JobContext
from agent.roles.retrieval_agent import RetrievalAgent
from agent.roles.investigation_agent import InvestigationAgent
from agent.roles.reporter_agent import ReporterAgent

try:
    from agent.llm.llama_client import LLaMAClient
except ImportError:
    LLaMAClient = None


def run_job(request: JobRequest, mode: str = "heuristic") -> JobResult:
    """
    Execute a log analysis job.

    Steps:
        1. Create job_id + job_dir
        2. Create execution plan (heuristic or LLM) and persist to plan.json
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

    # Check if job already exists (resume scenario)
    existing_state = read_job_state(job_dir)
    if existing_state:
        # Resume existing job
        return _resume_job(job_dir, existing_state, request, mode)

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

    # Set initial status to "queued"
    initial_state = {
        "job_id": job_id,
        "status": "queued",
        "query": request.query,
        "file_paths": request.file_paths,
        "mode": mode,
        "job_context": {
            "job_dir": context.job_dir,
            "artifacts_dir": context.artifacts_dir,
            "inputs_dir": context.inputs_dir,
            "input_files": context.input_files,
        },
        "queued_at": timing.started_at.isoformat() if timing.started_at else None,
    }
    write_job_state(job_dir, initial_state)

    # Update status to "running"
    update_job_state(job_dir, {
        "status": "running",
        "started_at": timing.started_at.isoformat() if timing.started_at else None,
    })

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

        # Create execution plan using new planner module
        try:
            plan = create_plan(planning_request, mode=mode)
            # Persist plan to plan.json
            plan_path = write_plan(job_dir, plan)
            if plan_path is None:
                warnings.append("Failed to persist execution plan to plan.json")
            planned_calls = plan.tool_calls
        except Exception as exc:
            errors.append(f"Planning failed: {exc}")
            # Fallback: create a default plan with error tool call
            from agent.planner.plan_models import Plan
            plan = Plan(
                mode=mode,
                tool_calls=[
                    ToolCall(
                        name="unknown",
                        status="pending",
                        arguments={},
                        summary=f"Planning failed: {exc}",
                    )
                ],
                reasoning=f"Planning failed with error: {exc}",
            )
            write_plan(job_dir, plan)
            planned_calls = plan.tool_calls

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

        # Run multi-agent workflow: Retrieval -> Investigation -> Reporter
        # Check for existing artifacts to avoid rerunning
        retrieval_results = None
        investigation_findings = None
        final_report = None

        try:
            # Step 1: Retrieval Agent (skip if retrieval.json exists)
            retrieval_path = os.path.join(job_dir, "retrieval.json")
            if check_artifact_exists(job_dir, "retrieval.json"):
                # Load existing retrieval results
                import json
                with open(retrieval_path, "r", encoding="utf-8") as f:
                    retrieval_results = json.load(f)
                warnings.append("Using existing retrieval.json - skipped retrieval agent")
            else:
                # Run retrieval agent
                retrieval_agent = RetrievalAgent(output_dir=job_dir)
                retrieval_results = retrieval_agent.retrieve_evidence(
                    file_path=request.file_paths[0] if request.file_paths else "",
                    query=request.query,
                    top_k=10,
                )
                retrieval_path = retrieval_agent.save_retrieval_results(
                    retrieval_results, retrieval_path
                )
            artifacts.append(artifact_ref_from_path(retrieval_path, from_tool="retrieval_agent"))

            # Step 2: Investigation Agent (skip if findings.json exists)
            findings_path = os.path.join(job_dir, "findings.json")
            if check_artifact_exists(job_dir, "findings.json"):
                # Load existing findings
                import json
                with open(findings_path, "r", encoding="utf-8") as f:
                    investigation_findings = json.load(f)
                warnings.append("Using existing findings.json - skipped investigation agent")
            else:
                # Run investigation agent
                investigation_agent = InvestigationAgent()
                investigation_findings = investigation_agent.investigate(
                    query=request.query,
                    retrieval_results=retrieval_results or {},
                    file_path=request.file_paths[0] if request.file_paths else None,
                )
                findings_path = investigation_agent.save_findings(
                    investigation_findings, findings_path
                )
            artifacts.append(artifact_ref_from_path(findings_path, from_tool="investigation_agent"))

            # Step 3: Reporter Agent (skip if final_answer.md exists)
            report_path = os.path.join(job_dir, "final_answer.md")
            if check_artifact_exists(job_dir, "final_answer.md"):
                # Load existing report
                with open(report_path, "r", encoding="utf-8") as f:
                    final_report = f.read()
                warnings.append("Using existing final_answer.md - skipped reporter agent")
            else:
                # Run reporter agent
                reporter_agent = ReporterAgent()
                final_report = reporter_agent.generate_report(
                    query=request.query,
                    retrieval_results=retrieval_results or {},
                    investigation_findings=investigation_findings or {},
                    job_id=job_id,
                )
                report_path = reporter_agent.save_report(
                    final_report, report_path
                )
            artifacts.append(artifact_ref_from_path(report_path, from_tool="reporter_agent"))

            # Use report as final answer if available
            if final_report:
                final_answer = final_report
            else:
                final_answer = _build_final_answer(
                    request, tool_results, artifacts, mode
                )
        except Exception as exc:
            # If agent workflow fails, fall back to standard answer building
            warnings.append(f"Multi-agent workflow failed: {exc}")
            final_answer = _build_final_answer(
                request, tool_results, artifacts, mode
            )

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
    llm_client: Any = None,
) -> str:
    """
    Build the final answer from tool results.

    If LLM is available and mode is "llm", use LLM to compose answer.
    Otherwise, combine tool summaries and artifact paths.
    """
    if mode == "llm" and (llm_client is not None or LLaMAClient is not None):
        try:
            client = llm_client or LLaMAClient
            return _build_final_answer_llm(request, tool_results, artifacts, client)
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
    llm_client: Any = None,
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
        client = llm_client or LLaMAClient()
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=os.getenv("LLAMA_MODEL", "llama-3.1-8b"),
            temperature=0.7,
        )
        return response.strip()
    except Exception:
        return _build_final_answer_heuristic(tool_results, artifacts)


def _resume_job(
    job_dir: str,
    existing_state: Dict[str, Any],
    request: JobRequest,
    mode: str,
) -> JobResult:
    """
    Resume an existing job by checking for existing artifacts and state.

    Args:
        job_dir: Path to job directory.
        existing_state: Existing job state dictionary.
        request: Job request.
        mode: Planning mode.

    Returns:
        JobResult with existing or completed state.
    """
    existing_status = existing_state.get("status", "unknown")

    # If job is already completed, return existing result
    if existing_status in ["succeeded", "failed", "succeeded_with_errors"]:
        # Try to reconstruct JobResult from existing state
        try:
            return JobResult.model_validate(existing_state)
        except Exception:
            pass

    # If job is queued or running, continue execution
    # This will check for existing artifacts and skip rerunning
    return run_job(request, mode)
