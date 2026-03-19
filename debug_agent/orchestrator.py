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

_FULL_FLOW = [
    StepKind.TRIAGE.value,
    StepKind.RCA.value,
    StepKind.EVIDENCE.value,
    StepKind.MEMORY.value,
    StepKind.EXPLANATION.value,
    StepKind.REMEDIATION.value,
    StepKind.REPORTING.value,
]


def run_debug_session(
    anomaly_id: str,
    *,
    run_id: Optional[str] = None,
    user_hint: Optional[str] = None,
) -> dict[str, Any]:
    """
    Run a full debug session for an anomaly.

    Planner-driven execution (full 7-agent pipeline):
    triage -> rca -> evidence -> memory -> explanation -> remediation -> reporting
    """
    context = DebugContext(anomaly_id=anomaly_id, run_id=run_id)
    planned_steps = plan_steps(context, user_hint=user_hint)
    steps = _ensure_full_pipeline_steps(planned_steps)
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
        elif kind == StepKind.REMEDIATION.value:
            triage = by_kind.get(StepKind.TRIAGE.value)
            rca = by_kind.get(StepKind.RCA.value)
            evidence = by_kind.get(StepKind.EVIDENCE.value)
            memory = by_kind.get(StepKind.MEMORY.value)
            explanation = by_kind.get(StepKind.EXPLANATION.value)
            if triage and triage.output:
                params.setdefault("triage_result", triage.output)
            if rca and rca.output:
                params.setdefault("rca_result", rca.output)
            if evidence and evidence.output:
                params.setdefault("evidence_result", evidence.output)
            if memory and memory.output:
                params.setdefault("memory_result", memory.output)
            if explanation and explanation.output:
                params.setdefault("explanation_result", explanation.output)
        elif kind == StepKind.REPORTING.value:
            triage = by_kind.get(StepKind.TRIAGE.value)
            rca = by_kind.get(StepKind.RCA.value)
            evidence = by_kind.get(StepKind.EVIDENCE.value)
            memory = by_kind.get(StepKind.MEMORY.value)
            explanation = by_kind.get(StepKind.EXPLANATION.value)
            remediation = by_kind.get(StepKind.REMEDIATION.value)
            if triage and triage.output:
                params.setdefault("triage_result", triage.output)
            if rca and rca.output:
                params.setdefault("rca_result", rca.output)
            if evidence and evidence.output:
                params.setdefault("evidence_result", evidence.output)
            if memory and memory.output:
                params.setdefault("memory_result", memory.output)
            if explanation and explanation.output:
                params.setdefault("explanation_result", explanation.output)
            if remediation and remediation.output:
                params.setdefault("remediation_result", remediation.output)

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
    # Include remediation in deterministic aggregate.
    remediation_result = by_kind.get(StepKind.REMEDIATION.value).output if by_kind.get(StepKind.REMEDIATION.value) else {}
    if isinstance(remediation_result, dict):
        if remediation_result.get("steps"):
            report.remediation_steps = [s for s in remediation_result.get("steps", []) if isinstance(s, str)]
        if remediation_result.get("optional_patch_direction"):
            report.optional_patch_direction = str(remediation_result.get("optional_patch_direction") or "")
        if remediation_result.get("confidence_note") and not report.confidence_summary:
            report.confidence_summary = str(remediation_result.get("confidence_note") or "")

    # Prefer reporting stage output when present (including reporting fallback payloads),
    # but always preserve deterministic RCA source-of-truth candidate ordering/identity.
    reporting_result = by_kind.get(StepKind.REPORTING.value)
    final_report_dict = report.to_dict()
    if reporting_result and isinstance(reporting_result.output, dict):
        rr = reporting_result.output
        out_report = rr.get("investigation_report")
        if isinstance(out_report, dict):
            # Never allow reporting stage to override deterministic RCA conclusions.
            out_report["root_cause_candidates"] = report.to_dict().get("root_cause_candidates", [])
            out_report["primary_candidate"] = report.to_dict().get("primary_candidate")
            out_report["confidence_summary"] = out_report.get("confidence_summary") or report.to_dict().get("confidence_summary", "")
            out_report["status"] = report.status.value
            final_report_dict = out_report
        if rr.get("final_report_summary"):
            final_report_dict["final_report_summary"] = str(rr.get("final_report_summary"))

    # Ensure required final output fields are always present even if downstream stages fail.
    final_report_dict.setdefault("triage_summary", report.triage_summary)
    final_report_dict.setdefault("root_cause_candidates", report.to_dict().get("root_cause_candidates", []))
    final_report_dict.setdefault("primary_candidate", report.to_dict().get("primary_candidate"))
    final_report_dict.setdefault("evidence_highlights", report.evidence_highlights)
    final_report_dict.setdefault("similar_incidents", report.similar_incidents)
    final_report_dict.setdefault("explanation_summary", report.explanation_summary)
    final_report_dict.setdefault("remediation_steps", report.remediation_steps)
    final_report_dict.setdefault("final_report_summary", report.final_report_summary)

    logger.info(
        "debug_agent.orchestrator.done anomaly_id=%s run_id=%s status=%s steps=%s explanation_ok=%s remediation_ok=%s reporting_ok=%s",
        anomaly_id,
        report.run_id,
        report.status.value,
        len(results),
        bool(by_kind.get(StepKind.EXPLANATION.value) and by_kind.get(StepKind.EXPLANATION.value).success),
        bool(by_kind.get(StepKind.REMEDIATION.value) and by_kind.get(StepKind.REMEDIATION.value).success),
        bool(by_kind.get(StepKind.REPORTING.value) and by_kind.get(StepKind.REPORTING.value).success),
    )

    return {
        "anomaly_id": anomaly_id,
        "run_id": report.run_id,
        "status": report.status.value,
        "investigation_report": final_report_dict,
        # Convenience top-level mirrors for required final output fields.
        "triage_summary": final_report_dict.get("triage_summary", ""),
        "root_cause_candidates": final_report_dict.get("root_cause_candidates", []),
        "primary_candidate": final_report_dict.get("primary_candidate"),
        "evidence_highlights": final_report_dict.get("evidence_highlights", []),
        "similar_incidents": final_report_dict.get("similar_incidents", []),
        "explanation_summary": final_report_dict.get("explanation_summary", ""),
        "remediation_steps": final_report_dict.get("remediation_steps", []),
        "final_report_summary": final_report_dict.get("final_report_summary", ""),
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


def _ensure_full_pipeline_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Ensure full pipeline presence and stable ordering:
      triage -> rca -> evidence -> memory -> explanation -> remediation -> reporting
    Planner remains source for existing dependency/optional metadata; missing steps are
    injected with conservative defaults.
    """
    by_kind: dict[str, dict[str, Any]] = {}
    for s in steps:
        kind = str(s.get("kind") or "")
        if kind:
            by_kind[kind] = dict(s)

    defaults: dict[str, dict[str, Any]] = {
        StepKind.TRIAGE.value: {
            "step_name": "triage_agent",
            "kind": StepKind.TRIAGE.value,
            "params": {},
            "depends_on": [],
            "optional": True,
        },
        StepKind.RCA.value: {
            "step_name": "rca_agent",
            "kind": StepKind.RCA.value,
            "params": {},
            "depends_on": [StepKind.TRIAGE.value],
            "optional": False,
        },
        StepKind.EVIDENCE.value: {
            "step_name": "evidence_agent",
            "kind": StepKind.EVIDENCE.value,
            "params": {},
            "depends_on": [StepKind.RCA.value],
            "optional": True,
        },
        StepKind.MEMORY.value: {
            "step_name": "memory_agent",
            "kind": StepKind.MEMORY.value,
            "params": {},
            "depends_on": [StepKind.EVIDENCE.value],
            "optional": True,
        },
        StepKind.EXPLANATION.value: {
            "step_name": "explanation_agent",
            "kind": StepKind.EXPLANATION.value,
            "params": {},
            "depends_on": [StepKind.EVIDENCE.value, StepKind.MEMORY.value],
            "optional": True,  # explanation optional
        },
        StepKind.REMEDIATION.value: {
            "step_name": "remediation_agent",
            "kind": StepKind.REMEDIATION.value,
            "params": {},
            "depends_on": [StepKind.RCA.value, StepKind.EVIDENCE.value],
            "optional": True,  # remediation optional
        },
        StepKind.REPORTING.value: {
            "step_name": "reporting_agent",
            "kind": StepKind.REPORTING.value,
            "params": {},
            "depends_on": [],
            "optional": False,
        },
    }

    ordered: list[dict[str, Any]] = []
    for kind in _FULL_FLOW:
        base = dict(defaults[kind])
        existing = by_kind.get(kind)
        if existing:
            # keep planner-provided values, but ensure all keys exist
            base.update(existing)
        ordered.append(base)
    return ordered


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
