"""Reporting agent: combine all agent outputs into final human-readable report."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict
from typing import Any, Optional

from debug_agent.langchain_schemas import parse_reporting_llm_output
from debug_agent.langchain_utils import json_payload
from debug_agent.shared_types import DebugContext, ReportStatus, ReportingPackage, StepKind, StepResult
from graphrag.llm_client import GraphRAGLLMClient, LLMConfig

logger = logging.getLogger(__name__)

_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+")

MINIMAL_REPORTING_SYSTEM_PROMPT = (
    "You are a technical incident reporter. You ONLY rephrase and polish wording using the provided "
    "deterministic_investigation JSON. You do NOT determine root cause, change candidate ordering, "
    "add incidents, files, commits, deployments, or evidence that are not already implied by the input. "
    "Do not contradict the primary candidate or confidence. "
    "Output strict JSON with exactly these keys: final_report_summary, executive_summary, investigation_narrative. "
    "final_report_summary: 2–4 sentences. executive_summary: 2–3 short lines. "
    "investigation_narrative: one concise paragraph linking triage → evidence → remediation. "
    "When a primary file path or file_id is present in the input, all three fields must mention it verbatim."
)


def _reporting_llm_enabled() -> bool:
    """Ollama-backed reporting when enabled; off via REPORTING_USE_OLLAMA=false."""
    explicit_off = os.getenv("REPORTING_USE_OLLAMA", "").strip().lower() in {"0", "false", "no"}
    if explicit_off:
        return False
    explicit_on = os.getenv("REPORTING_USE_OLLAMA", "").strip().lower() in {"1", "true", "yes"}
    if explicit_on:
        return True
    if os.getenv("DEBUG_AGENT_REPORTING_USE_LLM", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return bool(os.getenv("OLLAMA_HOST", "").strip())


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


def _deterministic_narrative(report: dict[str, Any]) -> str:
    """Short neutral narrative when LLM formatting is unavailable."""
    anomaly_id = str(report.get("anomaly_id") or "")
    primary = report.get("primary_candidate") or {}
    path = primary.get("path") or primary.get("file_id") or "unknown"
    triage = str(report.get("triage_summary") or "")[:200]
    return (
        f"Investigation for {anomaly_id}: triage noted {triage!r}. "
        f"Deterministic RCA highlights {path} as the leading candidate; "
        f"follow remediation steps and validate in staging."
    ).strip()


def _build_minimal_ollama_reporting_payload(report: dict[str, Any]) -> dict[str, Any]:
    """
    Grounding payload for Ollama — only fields that upstream agents produced.

    Excludes extra memory-derived narrative fields to reduce invention surface; formatting-only task.
    """
    primary = report.get("primary_candidate") if isinstance(report.get("primary_candidate"), dict) else {}
    candidates = report.get("root_cause_candidates") if isinstance(report.get("root_cause_candidates"), list) else []
    return {
        "anomaly_id": report.get("anomaly_id"),
        "triage_summary": str(report.get("triage_summary") or "")[:4000],
        "root_cause_candidates": [c for c in candidates[:8] if isinstance(c, dict)],
        "primary_candidate": primary,
        "confidence_summary": str(report.get("confidence_summary") or "")[:4000],
        "evidence_highlights": [str(x) for x in (report.get("evidence_highlights") or [])[:12] if isinstance(x, str)],
        "similar_incidents": (report.get("similar_incidents") or [])[:8],
        "explanation_summary": str(report.get("explanation_summary") or "")[:4000],
        "remediation_steps": [str(x) for x in (report.get("remediation_steps") or [])[:12] if isinstance(x, str)],
    }


def _build_reporting_llm_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias: minimal deterministic payload for the reporting LLM."""
    return _build_minimal_ollama_reporting_payload(report)


def _extract_path_like_tokens(text: str) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    out: list[str] = []
    for raw in _PATH_TOKEN_RE.findall(text):
        token = raw.strip("`'\"()[]{}.,:;")
        if token and token not in out:
            out.append(token)
    return out


def _allowed_path_tokens_from_report(report: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Paths and file_ids that may appear in polished text (deterministic RCA + grounded evidence)."""
    paths: set[str] = set()
    fids: set[str] = set()
    for c in report.get("root_cause_candidates") or []:
        if not isinstance(c, dict):
            continue
        p = str(c.get("path") or "").strip()
        fid = str(c.get("file_id") or "").strip()
        if p:
            paths.add(p)
        if fid:
            fids.add(fid)
    prim = report.get("primary_candidate") if isinstance(report.get("primary_candidate"), dict) else {}
    pp = str(prim.get("path") or "").strip()
    pf = str(prim.get("file_id") or "").strip()
    if pp:
        paths.add(pp)
    if pf:
        fids.add(pf)
    for line in report.get("evidence_highlights") or []:
        if isinstance(line, str):
            for t in _extract_path_like_tokens(line):
                paths.add(t)
    return paths, fids


def _output_paths_grounded(report: dict[str, Any], parsed: Any) -> bool:
    """Reject outputs that introduce path-like tokens not present in deterministic context."""
    allowed_paths, allowed_fids = _allowed_path_tokens_from_report(report)
    if not allowed_paths and not allowed_fids:
        return True
    blob = " ".join(
        [
            str(getattr(parsed, "final_report_summary", "") or ""),
            str(getattr(parsed, "executive_summary", "") or ""),
            str(getattr(parsed, "investigation_narrative", "") or ""),
        ]
    )
    for token in _extract_path_like_tokens(blob):
        if token in allowed_paths or token in allowed_fids:
            continue
        # Allow token to appear as substring of a longer allowed path (prefix match).
        if any(token in ap or ap in token for ap in allowed_paths if ap):
            continue
        if any(token in af or af in token for af in allowed_fids if af):
            continue
        logger.warning(
            "debug_agent.reporting_agent.grounding_failed unknown_path_token=%s",
            token[:120],
        )
        return False
    return True


def _grounding_valid(report: dict[str, Any], parsed: Any) -> bool:
    """Reject LLM output that omits the deterministic primary path/id (anti-hallucination)."""
    primary = report.get("primary_candidate") if isinstance(report.get("primary_candidate"), dict) else {}
    path = str(primary.get("path") or "").strip()
    fid = str(primary.get("file_id") or "").strip()
    if not path and not fid:
        return True
    blob = " ".join(
        [
            str(getattr(parsed, "final_report_summary", "") or ""),
            str(getattr(parsed, "executive_summary", "") or ""),
            str(getattr(parsed, "investigation_narrative", "") or ""),
        ]
    ).lower()
    if path and path.lower() in blob:
        if not _output_paths_grounded(report, parsed):
            return False
        return True
    if fid and fid.lower() in blob:
        if not _output_paths_grounded(report, parsed):
            return False
        return True
    logger.warning(
        "debug_agent.reporting_agent.grounding_failed primary_path=%s primary_file_id=%s",
        path[:80],
        fid[:16],
    )
    return False


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


def _looks_like_reporting_llm_failure(raw: dict[str, Any]) -> bool:
    """GraphRAGLLMClient may return explanation-shaped JSON when chat/parse fails."""
    lim = str(raw.get("limitations") or "")
    if "Provider failure" in lim:
        return True
    if "LLM response unavailable" in str(raw.get("explanation_summary") or ""):
        return True
    if ("primary_candidate" in raw or "ranked_hypotheses" in raw) and (
        "final_report_summary" not in raw or "executive_summary" not in raw
    ):
        return True
    return False


def _try_llm_formatting(
    *,
    report: dict[str, Any],
) -> Optional[tuple[str, str, str]]:
    """
    Ollama-backed polish (via GraphRAGLLMClient) — summarize/format only.

    On any failure or failed validation, returns None; caller uses deterministic text.
    """
    if not _reporting_llm_enabled():
        logger.info("debug_agent.reporting_agent.llm_skipped reason=reporting_llm_disabled")
        return None

    cfg = LLMConfig.from_env()
    logger.info(
        "debug_agent.reporting_agent.provider_selected provider=%s model=%s",
        cfg.provider,
        cfg.model,
    )
    if cfg.provider == "stub":
        logger.info("debug_agent.reporting_agent.llm_skipped reason=llm_provider_stub")
        return None

    user_payload = {
        "deterministic_investigation": _build_minimal_ollama_reporting_payload(report),
        "rules": {
            "must_not_change_root_cause": True,
            "must_not_reorder_candidates": True,
            "must_not_invent_entities": True,
            "use_only_provided_fields": True,
        },
    }
    user_prompt = json_payload(user_payload)

    logger.info(
        "debug_agent.reporting_agent.request_attempt provider=%s model=%s",
        cfg.provider,
        cfg.model,
    )
    llm = GraphRAGLLMClient(cfg)
    raw = llm.generate(system_prompt=MINIMAL_REPORTING_SYSTEM_PROMPT, user_prompt=user_prompt)

    if not isinstance(raw, dict):
        logger.warning("debug_agent.reporting_agent.llm_fallback reason=non_dict_response")
        return None
    if _looks_like_reporting_llm_failure(raw):
        logger.warning("debug_agent.reporting_agent.llm_fallback reason=provider_or_explanation_shaped_response")
        return None
    if "final_report_summary" not in raw or "executive_summary" not in raw:
        logger.warning("debug_agent.reporting_agent.llm_fallback reason=missing_reporting_keys")
        return None

    parsed = parse_reporting_llm_output(raw)
    if parsed is None:
        logger.warning("debug_agent.reporting_agent.llm_fallback reason=schema_validation_failed")
        return None

    final = (parsed.final_report_summary or "").strip()
    executive = (parsed.executive_summary or "").strip()
    narrative = (parsed.investigation_narrative or "").strip()
    if not final or not executive:
        logger.warning("debug_agent.reporting_agent.llm_fallback reason=empty_summary_fields")
        return None
    if not _grounding_valid(report, parsed):
        logger.warning("debug_agent.reporting_agent.llm_fallback reason=grounding_validation_failed")
        return None
    if not narrative:
        narrative = _deterministic_narrative(report)

    logger.info("debug_agent.reporting_agent.llm_success provider=%s", cfg.provider)
    return final, executive, narrative


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
        investigation_narrative = _deterministic_narrative(report)
        llm_fmt = _try_llm_formatting(report=report)
        source = "deterministic"
        if llm_fmt:
            final_summary, executive_summary, investigation_narrative = llm_fmt
            source = "ollama_assisted"
        report["investigation_narrative"] = investigation_narrative
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
            investigation_narrative=investigation_narrative,
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
        fb_narr = _deterministic_narrative(fallback_report)
        fallback_report["investigation_narrative"] = fb_narr
        fallback = ReportingPackage(
            anomaly_id=anomaly_id,
            final_report_summary=final_summary,
            investigation_report=fallback_report,
            executive_summary=executive_summary,
            investigation_narrative=fb_narr,
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
