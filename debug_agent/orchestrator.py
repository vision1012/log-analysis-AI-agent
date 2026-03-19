"""Orchestrator: executes planner-driven debug flow and aggregates investigation outputs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from debug_agent.planner import plan_steps
from debug_agent.shared_types import (
    DebugContext,
    InvestigationReport,
    ReportStatus,
    RootCauseCandidate,
    StepKind,
    StepResult,
)

logger = logging.getLogger(__name__)


def run_debug_session(
    anomaly_id: str,
    *,
    run_id: Optional[str] = None,
    user_hint: Optional[str] = None,
) -> dict[str, Any]:
    """
    Run a full debug session for an anomaly.

    Planner-driven execution (Wave 2 capable):
    triage -> rca -> evidence -> memory -> explanation
    """
    context = DebugContext(anomaly_id=anomaly_id, run_id=run_id)
    steps = plan_steps(context, user_hint=user_hint)
    results: list[StepResult] = []
    by_kind: dict[str, StepResult] = {}

    logger.info(
        "debug_agent.orchestrator.start anomaly_id=%s run_id=%s planned_steps=%s",
        anomaly_id,
        run_id,
        len(steps),
    )

    optional_by_kind: dict[str, bool] = {}
    for step_desc in steps:
        k = str(step_desc.get("kind", ""))
        optional_by_kind[k] = bool(step_desc.get("optional", False))

    for step_desc in steps:
        kind = step_desc.get("kind", "")
        params = dict(step_desc.get("params") or {})
        depends_on = list(step_desc.get("depends_on") or [])
        optional = bool(step_desc.get("optional", False))

        # Enforce deterministic planner dependencies.
        missing_deps: list[str] = []
        for dep in depends_on:
            dep_result = by_kind.get(dep)
            # If optional dependency fails/missing, degrade safely and continue.
            if dep_result is None or not dep_result.success:
                if optional_by_kind.get(dep, False):
                    logger.info(
                        "debug_agent.orchestrator.degrade kind=%s optional_dep=%s reason=%s",
                        kind,
                        dep,
                        "missing" if dep_result is None else "failed",
                    )
                    continue
                missing_deps.append(dep)
        if missing_deps:
            err = f"skipped; unmet dependencies: {', '.join(missing_deps)}"
            logger.warning(
                "debug_agent.orchestrator.skip kind=%s optional=%s reason=%s",
                kind,
                optional,
                err,
            )
            result = StepResult(step_kind=_safe_step_kind(kind), success=False, output={}, error=err)
            results.append(result)
            by_kind[kind] = result
            if not optional:
                break
            continue

        # Propagate prior agent outputs to downstream steps.
        if kind == StepKind.RCA.value:
            triage = by_kind.get(StepKind.TRIAGE.value)
            if triage and triage.output:
                params.setdefault("triage_result", triage.output)
        elif kind == StepKind.EVIDENCE.value:
            rca = by_kind.get(StepKind.RCA.value)
            if rca and rca.output:
                params.setdefault("rca_result", rca.output)
            triage = by_kind.get(StepKind.TRIAGE.value)
            if triage and triage.output:
                params.setdefault("triage_result", triage.output)
        elif kind == StepKind.MEMORY.value:
            rca = by_kind.get(StepKind.RCA.value)
            if rca and rca.output:
                params.setdefault("rca_result", rca.output)
            triage = by_kind.get(StepKind.TRIAGE.value)
            if triage and triage.output:
                params.setdefault("triage_result", triage.output)
        elif kind == StepKind.EXPLANATION.value:
            rca = by_kind.get(StepKind.RCA.value)
            evidence = by_kind.get(StepKind.EVIDENCE.value)
            memory = by_kind.get(StepKind.MEMORY.value)
            if rca and rca.output:
                params.setdefault("rca_result", rca.output)
                params.setdefault("run_id", (rca.output or {}).get("run_id"))
            if evidence and evidence.output:
                params.setdefault("evidence_result", evidence.output)
            if memory and memory.output:
                params.setdefault("memory_result", memory.output)

        result = _execute_step(kind, context, params)
        results.append(result)
        by_kind[kind] = result

        logger.info(
            "debug_agent.orchestrator.step kind=%s success=%s error=%s",
            kind,
            result.success,
            result.error or "",
        )

    report = _build_report(
        anomaly_id=anomaly_id,
        default_run_id=run_id,
        triage_result=(by_kind.get(StepKind.TRIAGE.value).output if by_kind.get(StepKind.TRIAGE.value) else {}),
        rca_result=(by_kind.get(StepKind.RCA.value).output if by_kind.get(StepKind.RCA.value) else {}),
        evidence_result=(by_kind.get(StepKind.EVIDENCE.value).output if by_kind.get(StepKind.EVIDENCE.value) else {}),
        memory_result=(by_kind.get(StepKind.MEMORY.value).output if by_kind.get(StepKind.MEMORY.value) else {}),
        explanation_result=(by_kind.get(StepKind.EXPLANATION.value).output if by_kind.get(StepKind.EXPLANATION.value) else {}),
        step_results=results,
    )

    logger.info(
        "debug_agent.orchestrator.done anomaly_id=%s run_id=%s status=%s steps=%s",
        anomaly_id,
        report.run_id,
        report.status.value,
        len(results),
    )

    return {
        "anomaly_id": anomaly_id,
        "run_id": report.run_id,
        "status": report.status.value,
        "investigation_report": report.to_dict(),
        "steps": [
            {
                "kind": r.step_kind.value,
                "success": r.success,
                "output": r.output,
                "error": r.error,
            }
            for r in results
        ],
    }


def _safe_step_kind(kind: str) -> StepKind:
    """Parse step kind safely for synthetic StepResult values."""
    try:
        return StepKind(kind)
    except ValueError:
        return StepKind.RCA


def _root_candidates_from_rca_output(rca_output: dict[str, Any]) -> list[RootCauseCandidate]:
    """Normalize root cause candidates from RCA agent output."""
    raw = rca_output.get("candidates") if isinstance(rca_output, dict) else []
    if not isinstance(raw, list):
        return []
    out: list[RootCauseCandidate] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        out.append(
            RootCauseCandidate(
                rank=int(c.get("rank") or 0),
                file_id=str(c.get("file_id") or ""),
                path=str(c.get("path") or ""),
                confidence=float(c.get("confidence") or 0.0),
                evidence_ref=str(c.get("evidence_ref") or ""),
            )
        )
    return sorted(out, key=lambda x: (x.rank or 10_000))


def _build_report(
    *,
    anomaly_id: str,
    default_run_id: Optional[str],
    triage_result: dict[str, Any],
    rca_result: dict[str, Any],
    evidence_result: dict[str, Any],
    memory_result: dict[str, Any],
    explanation_result: dict[str, Any],
    step_results: list[StepResult],
) -> InvestigationReport:
    """Aggregate planner outputs into an enriched investigation report."""
    root_candidates = _root_candidates_from_rca_output(rca_result)
    primary = root_candidates[0] if root_candidates else None
    run_id = str(rca_result.get("run_id") or default_run_id or "")

    evidence_bullets = evidence_result.get("bullets") if isinstance(evidence_result, dict) else []
    explanation_highlights = explanation_result.get("evidence_highlights") if isinstance(explanation_result, dict) else []
    merged_highlights: list[str] = []
    for line in (evidence_bullets or []) + (explanation_highlights or []):
        if isinstance(line, str) and line and line not in merged_highlights:
            merged_highlights.append(line)

    confidence_summary = ""
    if isinstance(explanation_result, dict):
        confidence_summary = str(explanation_result.get("confidence_alignment_note") or "")
    if not confidence_summary and primary:
        confidence_summary = f"Deterministic RCA top candidate confidence: {primary.confidence:.2f}"
    if not confidence_summary:
        confidence_summary = "Deterministic RCA confidence not available."

    explanation_summary = ""
    if isinstance(explanation_result, dict):
        explanation_summary = str(explanation_result.get("explanation_summary") or "")
    if not explanation_summary and primary:
        explanation_summary = f"Top deterministic RCA candidate: {primary.path or primary.file_id}."
    if not explanation_summary:
        explanation_summary = "No explanation available."

    triage_summary = ""
    if isinstance(triage_result, dict):
        triage_summary = str(triage_result.get("summary") or "")
        if not triage_summary:
            sev = str(triage_result.get("severity") or triage_result.get("priority") or "")
            err_type = str(triage_result.get("error_type") or triage_result.get("classification") or "")
            if sev or err_type:
                triage_summary = f"Triage context: severity={sev or 'unknown'}, error_type={err_type or 'unknown'}."
    if not triage_summary:
        triage_summary = "Triage context unavailable."

    similar_incidents = memory_result.get("similar_incidents") if isinstance(memory_result, dict) else []
    if not isinstance(similar_incidents, list):
        similar_incidents = []
    historical_patterns_summary = ""
    recurrence_signals: dict[str, Any] = {}
    if isinstance(memory_result, dict):
        historical_patterns_summary = str(memory_result.get("historical_patterns_summary") or "")
        recurrence_signals = {
            "recurrence_score": memory_result.get("recurrence_score", 0.0),
            "prior_root_causes_count": len(memory_result.get("prior_root_causes") or []),
            "prior_attributions_count": len(memory_result.get("prior_attributions") or []),
        }
    if not historical_patterns_summary:
        historical_patterns_summary = "No historical pattern summary available."

    remediation_steps: list[str] = []
    if isinstance(explanation_result, dict):
        patch = explanation_result.get("metadata", {}).get("optional_patch_direction", "")
    else:
        patch = ""
    optional_patch_direction = str(patch or "")

    # RCA is required source-of-truth step; explanation/evidence may fail partially.
    rca_ok = any(r.step_kind == StepKind.RCA and r.success for r in step_results)
    all_ok = all(r.success for r in step_results) if step_results else False
    if not rca_ok:
        status = ReportStatus.FAILED
    elif all_ok:
        status = ReportStatus.COMPLETED
    else:
        status = ReportStatus.PARTIAL

    return InvestigationReport(
        anomaly_id=anomaly_id,
        run_id=run_id or None,
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        triage_summary=triage_summary,
        root_cause_candidates=root_candidates,
        primary_candidate=primary,
        confidence_summary=confidence_summary,
        evidence_highlights=merged_highlights[:12],
        similar_incidents=similar_incidents,
        historical_patterns_summary=historical_patterns_summary,
        recurrence_signals=recurrence_signals,
        explanation_summary=explanation_summary,
        remediation_steps=remediation_steps,
        optional_patch_direction=optional_patch_direction,
        final_report_summary=(
            "Wave 2 investigation completed with deterministic RCA as source of truth."
            if rca_ok else
            "Investigation failed before deterministic RCA candidates were available."
        ),
    )


_AGENT_MAP = {
    StepKind.RCA.value: "debug_agent.rca_agent",
    StepKind.EVIDENCE.value: "debug_agent.evidence_agent",
    StepKind.EXPLANATION.value: "debug_agent.explanation_agent",
    StepKind.TRIAGE.value: "debug_agent.triage_agent",
    StepKind.MEMORY.value: "debug_agent.memory_agent",
    StepKind.REMEDIATION.value: "debug_agent.remediation_agent",
    StepKind.REPORTING.value: "debug_agent.reporting_agent",
}


def _execute_step(
    kind: str,
    context: DebugContext,
    params: dict[str, Any],
) -> StepResult:
    """Execute a single step by delegating to the appropriate agent."""
    try:
        step_kind = StepKind(kind)
    except ValueError:
        return StepResult(step_kind=StepKind.RCA, success=False, error=f"Unknown step kind: {kind}")

    module_path = _AGENT_MAP.get(kind)
    if not module_path:
        return StepResult(step_kind=step_kind, success=False, error=f"No agent for kind: {kind}")

    try:
        import importlib
        mod = importlib.import_module(module_path)
        return mod.run(context, params=params)
    except Exception as e:
        return StepResult(step_kind=step_kind, success=False, error=str(e))
