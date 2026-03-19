"""Reporting agent: combine all agent outputs into final human-readable report."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from typing import Any, Optional

from debug_agent.langchain_schemas import parse_reporting_llm_output
from debug_agent.langchain_utils import invoke_llm, invoke_with_safe_fallback, json_payload, render_prompt
from debug_agent.shared_types import DebugContext, ReportStatus, ReportingPackage, StepKind, StepResult
from graphrag.llm_client import GraphRAGLLMClient, LLMConfig

logger = logging.getLogger(__name__)


def _to_float(v: Any, default: float = 0.0) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _deterministic_summary(report: dict[str, Any]) -> tuple[str, str]:
    """Create deterministic human-friendly summaries from structured report."""
    anomaly_id = str(report.get("anomaly_id") or "")
    triage = str(report.get("triage_summary") or "Triage context unavailable.")
    primary = report.get("primary_candidate") or {}
    primary_path = primary.get("path") or primary.get("file_id") or "unknown"
    conf = _to_float(primary.get("confidence"), 0.0)
    evidence_count = len(report.get("evidence_highlights") or [])
    similar_count = len(report.get("similar_incidents") or [])
    explanation = str(report.get("explanation_summary") or "No explanation available.")
    remediation_steps = report.get("remediation_steps") or []
    first_action = remediation_steps[0] if remediation_steps else "Apply reversible mitigation and monitor impact."

    final = (
        f"Anomaly {anomaly_id}: {triage} "
        f"Deterministic RCA identifies {primary_path} as the top root cause candidate "
        f"(confidence {conf:.2f}). "
        f"Supporting evidence includes {evidence_count} highlights with {similar_count} similar incidents. "
        f"Recommended action: {first_action}"
    )
    executive = (
        f"Top cause: {primary_path} ({conf:.2f}).\n"
        f"Evidence: {evidence_count} highlights; similar incidents: {similar_count}.\n"
        f"Next action: {first_action}"
    )
    if explanation and explanation not in final:
        final += f" Explanation: {explanation}"
    return final.strip(), executive.strip()


def _grounded_evidence_highlights(
    *,
    report_highlights: Any,
    evidence_output: dict[str, Any],
    explanation_output: dict[str, Any],
) -> list[str]:
    """
    Clamp evidence highlights to known deterministic/explanation evidence only.

    Prevents invented evidence text from entering final reporting payload.
    """
    allowed: list[str] = []
    for line in (evidence_output.get("bullets") or []) + (explanation_output.get("evidence_highlights") or []):
        if isinstance(line, str) and line and line not in allowed:
            allowed.append(line)

    proposed = report_highlights if isinstance(report_highlights, list) else []
    grounded = [x for x in proposed if isinstance(x, str) and x in allowed]
    if grounded:
        return grounded[:8]
    if allowed:
        return allowed[:8]
    return []


def _deterministic_report(
    *,
    anomaly_id: str,
    triage: dict[str, Any],
    rca: dict[str, Any],
    evidence: dict[str, Any],
    memory: dict[str, Any],
    explanation: dict[str, Any],
    remediation: dict[str, Any],
    base_report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Build a deterministic structured report while enforcing RCA/evidence guardrails.

    RCA candidates/ordering/confidence remain source of truth from RCA output.
    """
    report = dict(base_report or {})
    candidates = rca.get("candidates") if isinstance(rca.get("candidates"), list) else []
    primary = rca.get("primary") if isinstance(rca.get("primary"), dict) else {}
    if not primary and candidates:
        first = candidates[0]
        primary = first if isinstance(first, dict) else {}

    report["anomaly_id"] = anomaly_id
    report["run_id"] = rca.get("run_id") or report.get("run_id")
    report["status"] = str(report.get("status") or "partial").lower()
    report["triage_summary"] = str(report.get("triage_summary") or triage.get("summary") or "")
    # Guardrail: never let reporting stage alter deterministic RCA conclusions.
    report["root_cause_candidates"] = [c for c in candidates if isinstance(c, dict)]
    report["primary_candidate"] = primary if isinstance(primary, dict) else {}
    report["confidence_summary"] = str(
        report.get("confidence_summary")
        or explanation.get("confidence_alignment_note")
        or remediation.get("confidence_note")
        or ""
    )
    report["evidence_highlights"] = _grounded_evidence_highlights(
        report_highlights=report.get("evidence_highlights"),
        evidence_output=evidence if isinstance(evidence, dict) else {},
        explanation_output=explanation if isinstance(explanation, dict) else {},
    )
    report["similar_incidents"] = memory.get("similar_incidents") if isinstance(memory.get("similar_incidents"), list) else []
    report["historical_patterns_summary"] = str(memory.get("historical_patterns_summary") or "")
    report["recurrence_signals"] = {
        "recurrence_score": memory.get("recurrence_score", 0.0),
        "prior_root_causes_count": len(memory.get("prior_root_causes") or []),
    }
    report["explanation_summary"] = str(explanation.get("explanation_summary") or report.get("explanation_summary") or "")
    report["remediation_steps"] = remediation.get("steps") if isinstance(remediation.get("steps"), list) else []
    report["optional_patch_direction"] = str(remediation.get("optional_patch_direction") or "")
    return report


def _try_llm_formatting(
    *,
    report: dict[str, Any],
) -> Optional[tuple[str, str]]:
    """Optional LLM formatting for readability; never changes structured conclusions."""
    enabled = os.getenv("DEBUG_AGENT_REPORTING_USE_LLM", "false").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return None

    system_prompt = (
        "You format incident reports. Use only provided structured report data. "
        "Do not alter RCA conclusions, candidate order, or confidence values. "
        "Return strict JSON: {\"final_report_summary\": string, \"executive_summary\": string}."
    )
    user_payload = {
        "report": report,
        "rules": {
            "must_not_change_root_cause": True,
            "must_not_change_ranking": True,
            "must_not_change_confidence": True,
            "executive_summary_lines": "2-3",
        },
    }
    user_prompt = render_prompt("{payload_json}", payload_json=json_payload(user_payload))
    cfg = LLMConfig.from_env()
    llm = GraphRAGLLMClient(cfg)
    raw = invoke_with_safe_fallback(
        primary_call=lambda: invoke_llm(system_prompt=system_prompt, user_prompt=user_prompt, config=cfg),
        fallback_call=lambda: llm.generate(system_prompt=system_prompt, user_prompt=user_prompt),
        context="reporting_agent",
    )
    if not isinstance(raw, dict):
        return None
    parsed = parse_reporting_llm_output(raw)
    if parsed is None:
        return None
    final = parsed.final_report_summary
    executive = parsed.executive_summary
    if not final.strip():
        return None
    if not executive.strip():
        return None
    return final.strip(), executive.strip()


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Build final reporting package from all agent outputs.

    Inputs:
      - triage_result
      - rca_result
      - evidence_result
      - memory_result
      - explanation_result
      - remediation_result
      - investigation_report (optional pre-aggregated)
    """
    payload = params or {}
    anomaly_id = str(payload.get("anomaly_id") or context.anomaly_id or "")
    if not anomaly_id:
        return StepResult(step_kind=StepKind.REPORTING, success=False, output={}, error="missing anomaly_id")

    logger.info("debug_agent.reporting_agent.start anomaly_id=%s", anomaly_id)
    try:
        report = payload.get("investigation_report") if isinstance(payload.get("investigation_report"), dict) else {}
        triage = payload.get("triage_result") if isinstance(payload.get("triage_result"), dict) else {}
        rca = payload.get("rca_result") if isinstance(payload.get("rca_result"), dict) else {}
        evidence = payload.get("evidence_result") if isinstance(payload.get("evidence_result"), dict) else {}
        memory = payload.get("memory_result") if isinstance(payload.get("memory_result"), dict) else {}
        explanation = payload.get("explanation_result") if isinstance(payload.get("explanation_result"), dict) else {}
        remediation = payload.get("remediation_result") if isinstance(payload.get("remediation_result"), dict) else {}

        # Build/sanitize structured report with deterministic RCA and grounded evidence guardrails.
        report = _deterministic_report(
            anomaly_id=anomaly_id,
            triage=triage,
            rca=rca,
            evidence=evidence,
            memory=memory,
            explanation=explanation,
            remediation=remediation,
            base_report=report if report else None,
        )

        final_summary, executive_summary = _deterministic_summary(report)
        llm_fmt = _try_llm_formatting(report=report)
        source = "deterministic"
        if llm_fmt:
            final_summary, executive_summary = llm_fmt
            source = "llm_assisted"
        logger.info(
            "debug_agent.reporting_agent.format anomaly_id=%s source=%s candidates=%s evidence=%s",
            anomaly_id,
            source,
            len(report.get("root_cause_candidates") or []),
            len(report.get("evidence_highlights") or []),
        )

        status_raw = str(report.get("status") or "").lower()
        if status_raw == ReportStatus.COMPLETED.value:
            status = ReportStatus.COMPLETED
        elif status_raw == ReportStatus.FAILED.value:
            status = ReportStatus.FAILED
        else:
            status = ReportStatus.PARTIAL

        out = ReportingPackage(
            anomaly_id=anomaly_id,
            final_report_summary=final_summary,
            investigation_report=report,
            executive_summary=executive_summary,
            final_summary=final_summary,  # compatibility alias
            status=status,
            metadata={"source": source},
        )
        logger.info(
            "debug_agent.reporting_agent.done anomaly_id=%s status=%s source=%s",
            anomaly_id,
            out.status.value,
            source,
        )
        return StepResult(step_kind=StepKind.REPORTING, success=True, output=asdict(out), error=None)
    except Exception as exc:
        logger.exception("debug_agent.reporting_agent.error anomaly_id=%s error=%s", anomaly_id, str(exc))
        fallback_report = {"anomaly_id": anomaly_id, "status": "partial", "triage_summary": "Reporting fallback used."}
        final_summary, executive_summary = _deterministic_summary(fallback_report)
        fallback = ReportingPackage(
            anomaly_id=anomaly_id,
            final_report_summary=final_summary,
            investigation_report=fallback_report,
            executive_summary=executive_summary,
            final_summary=final_summary,
            status=ReportStatus.PARTIAL,
            metadata={"source": "fallback"},
        )
        return StepResult(
            step_kind=StepKind.REPORTING,
            success=False,
            output=asdict(fallback),
            error=f"reporting_agent failed: {exc}",
        )
