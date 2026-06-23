"""Orchestrate deterministic RCA explanation generation for GraphRAG."""

from __future__ import annotations

import logging
from typing import Any, Optional

from artifacts.evidence_store import EvidenceStore
from graph.neo4j_client import Neo4jClient
from graphrag.context_packer import pack_context
from graphrag.evidence_summarizer import summarize_evidence
from graphrag.narrative_generator import attach_narrative_to_output, generate_investigation_narrative
from graphrag.output_validator import validate_or_repair_output
from graphrag.prompt_builder import build_minimal_deterministic_prompt
from rca_engine.confidence_engine import build_confidence_reasoning

logger = logging.getLogger(__name__)


def _string_bullets(summarized_evidence: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for b in summarized_evidence:
        t = b.get("text")
        if isinstance(t, str) and t:
            out.append(t)
    return out


def _deterministic_ranked_hypotheses(context_pack: dict[str, Any], *, top_n: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    candidates = context_pack.get("candidates") or []
    for c in candidates[:top_n]:
        out.append(
            {
                "rank": c.get("rank"),
                "file_id": c.get("file_id"),
                "path": c.get("path"),
                "confidence": c.get("confidence"),
                "hypothesis": "Deterministic RCA candidate from graph evidence.",
                "evidence_ref": c.get("evidence_ref") or "",
            }
        )
    return out


def _fallback_output(
    context_pack: dict[str, Any],
    summarized_evidence: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, Any]:
    deterministic = _deterministic_ranked_hypotheses(context_pack, top_n=3)
    primary = deterministic[0] if deterministic else {
        "rank": 1,
        "file_id": "",
        "path": "",
        "confidence": 0.0,
        "evidence_ref": "",
    }
    return {
        "anomaly_id": context_pack.get("anomaly_id") or "",
        "primary_candidate": {
            "rank": primary.get("rank", 1),
            "file_id": primary.get("file_id", ""),
            "path": primary.get("path", ""),
            "confidence": primary.get("confidence", 0.0),
            "evidence_ref": primary.get("evidence_ref", ""),
        },
        "ranked_hypotheses": deterministic,
        "explanation_summary": "Could not produce a validated model explanation; deterministic RCA ranking is returned.",
        "evidence_highlights": _string_bullets(summarized_evidence)[:8],
        "confidence_alignment_note": "Deterministic ranking and confidence remain the source of truth.",
        "optional_patch_direction": "",
        "limitations": "; ".join(errors[:4]) if errors else "LLM output validation failed.",
    }


def _primary_confidence_assessment(context_pack: dict[str, Any]) -> dict[str, Any]:
    candidates = context_pack.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return {}
    top = candidates[0] if isinstance(candidates[0], dict) else {}
    assessment = top.get("confidence_assessment")
    return dict(assessment) if isinstance(assessment, dict) else {}


def _attach_confidence_explanation(output: dict[str, Any], context_pack: dict[str, Any]) -> dict[str, Any]:
    """Add confidence engine reasoning without changing deterministic ranking."""
    assessment = _primary_confidence_assessment(context_pack)
    if assessment:
        output["confidence_assessment"] = assessment
        output["confidence_reasoning"] = build_confidence_reasoning(assessment)
    else:
        output.setdefault("confidence_assessment", {})
        output.setdefault(
            "confidence_reasoning",
            "Confidence assessment unavailable; deterministic ranking score remains authoritative.",
        )
    return output


def _attach_supplementary_context(
    output: dict[str, Any],
    *,
    context_pack: dict[str, Any],
) -> dict[str, Any]:
    """Expose packed supplementary context on the explanation output (additive)."""
    for key in (
        "jira_ticket_context",
        "feedback_context",
        "similar_incident_context",
        "multi_agent_findings",
    ):
        value = context_pack.get(key)
        if value:
            output[key] = value
    investigation_context = context_pack.get("investigation_context") or {}
    previous = investigation_context.get("previous_investigations")
    if previous:
        output["previous_investigations"] = previous
    return output


def _finalize_explanation_output(
    output: dict[str, Any],
    *,
    context_pack: dict[str, Any],
    unified_investigation_context: Any | None = None,
) -> dict[str, Any]:
    with_narrative = _attach_investigation_narrative(
        output,
        context_pack=context_pack,
        unified_investigation_context=unified_investigation_context,
    )
    with_confidence = _attach_confidence_explanation(with_narrative, context_pack)
    return _attach_supplementary_context(with_confidence, context_pack=context_pack)


def _attach_investigation_narrative(
    output: dict[str, Any],
    *,
    context_pack: dict[str, Any],
    unified_investigation_context: Any | None = None,
) -> dict[str, Any]:
    """Add timeline/causal narrative without changing deterministic RCA fields."""
    try:
        narrative = generate_investigation_narrative(
            {"candidates": context_pack.get("candidates") or [], "ranked_hypotheses": output.get("ranked_hypotheses") or []},
            unified_context=unified_investigation_context,
            graph_context=context_pack.get("investigation_context") or {},
            supplementary_context={
                "jira_ticket_context": context_pack.get("jira_ticket_context") or {},
                "feedback_context": context_pack.get("feedback_context") or {},
                "similar_incident_context": context_pack.get("similar_incident_context") or {},
                "multi_agent_findings": context_pack.get("multi_agent_findings") or {},
            },
        )
        return attach_narrative_to_output(output, narrative)
    except Exception as exc:
        logger.warning("graphrag.explanation_generator.narrative_failed err=%s", exc)
        return output


def _allowed_evidence_strings(summarized_evidence: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for b in summarized_evidence:
        t = b.get("text") if isinstance(b, dict) else None
        if isinstance(t, str) and t.strip() and t not in out:
            out.append(t)
    return out


def _ground_evidence_highlights(
    proposed: Any,
    summarized_evidence: list[dict[str, Any]],
) -> list[str]:
    """Keep only highlights that match deterministic evidence strings (anti-hallucination)."""
    allowed = _allowed_evidence_strings(summarized_evidence)
    allowed_set = set(allowed)
    if not isinstance(proposed, list):
        return allowed[:8]
    grounded = [x for x in proposed if isinstance(x, str) and x in allowed_set]
    if grounded:
        return grounded[:8]
    return allowed[:8]


def _merge_llm_text_into_deterministic_contract(
    raw: dict[str, Any],
    *,
    context_pack: dict[str, Any],
    summarized_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Combine partial LLM JSON (text fields only) with deterministic primary + ranked hypotheses.

    Ignores any primary_candidate / ranked_hypotheses from the model so ranking cannot be overridden.
    """
    deterministic = _deterministic_ranked_hypotheses(context_pack, top_n=3)
    primary_row = deterministic[0] if deterministic else {}
    primary_obj = {
        "rank": int(primary_row.get("rank") or 1),
        "file_id": str(primary_row.get("file_id") or ""),
        "path": str(primary_row.get("path") or ""),
        "confidence": float(primary_row.get("confidence") or 0.0),
        "evidence_ref": str(primary_row.get("evidence_ref") or ""),
    }
    highlights = _ground_evidence_highlights(
        raw.get("evidence_highlights"),
        summarized_evidence,
    )
    aid = str(context_pack.get("anomaly_id") or "")
    if raw.get("anomaly_id") is not None and str(raw.get("anomaly_id")) != aid:
        logger.warning(
            "graphrag.explanation_generator merge anomaly_id mismatch llm=%s deterministic=%s",
            raw.get("anomaly_id"),
            aid,
        )
    return {
        "anomaly_id": aid,
        "primary_candidate": primary_obj,
        "ranked_hypotheses": deterministic,
        "explanation_summary": str(raw.get("explanation_summary") or ""),
        "evidence_highlights": highlights,
        "confidence_alignment_note": str(raw.get("confidence_alignment_note") or ""),
        "optional_patch_direction": str(raw.get("optional_patch_direction") or ""),
        "limitations": str(raw.get("limitations") or ""),
    }


def _validate_against_context(
    output: dict[str, Any],
    context_pack: dict[str, Any],
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    required = (
        "anomaly_id",
        "primary_candidate",
        "ranked_hypotheses",
        "explanation_summary",
        "evidence_highlights",
        "confidence_alignment_note",
        "optional_patch_direction",
        "limitations",
    )
    for k in required:
        if k not in output:
            errors.append(f"missing key: {k}")

    if output.get("anomaly_id") != context_pack.get("anomaly_id"):
        errors.append("anomaly_id mismatch with deterministic context")

    deterministic = context_pack.get("candidates") or []
    allowed_file_ids = {c.get("file_id") for c in deterministic if isinstance(c, dict)}
    expected_ranks = [c.get("rank") for c in deterministic[:3] if isinstance(c, dict)]

    primary = output.get("primary_candidate") or {}
    if primary:
        pfid = primary.get("file_id")
        if pfid not in allowed_file_ids:
            errors.append("primary_candidate.file_id not in deterministic candidates")

    ranked = output.get("ranked_hypotheses") or []
    if not isinstance(ranked, list):
        errors.append("ranked_hypotheses must be list")
        ranked = []

    out_ranks = [r.get("rank") for r in ranked if isinstance(r, dict)]
    if expected_ranks and out_ranks[: len(expected_ranks)] != expected_ranks[: len(out_ranks)]:
        errors.append("ranked_hypotheses order does not match deterministic ranking")

    for h in ranked:
        if not isinstance(h, dict):
            errors.append("ranked_hypotheses contains non-object item")
            continue
        if h.get("file_id") not in allowed_file_ids:
            errors.append("ranked_hypotheses contains file_id not in deterministic candidates")

    return (len(errors) == 0, errors)


def generate_explanation(
    anomaly_id: str,
    *,
    graph_client: Neo4jClient,
    evidence_store: EvidenceStore,
    llm_client: Any,
    run_id: Optional[str] = None,
    user_instruction: Optional[str] = None,
    unified_investigation_context: Any | None = None,
    investigation_id: Optional[str] = None,
    service_name: Optional[str] = None,
    ticket_key: Optional[str] = None,
    alert_id: Optional[str] = None,
    multi_agent_report: Any | None = None,
) -> dict[str, Any]:
    """
    Generate explanation for the latest deterministic RCA run (or provided run_id).

    Pipeline:
      1) pack context
      2) summarize evidence
      3) build minimal deterministic-only prompt (Ollama / local LLM)
      4) call LLM (HTTP via GraphRAGLLMClient when provider=ollama)
      5) merge assistive text with deterministic candidates (ranking never overridden)
      6) validate / repair / safe fallback
    """
    _ = user_instruction  # API compatibility; minimal prompt uses deterministic context only

    context_pack = pack_context(
        anomaly_id,
        graph_client=graph_client,
        evidence_store=evidence_store,
        run_id=run_id,
        investigation_id=investigation_id,
        service_name=service_name,
        ticket_key=ticket_key,
        alert_id=alert_id,
        unified_investigation_context=unified_investigation_context,
        multi_agent_report=multi_agent_report,
        max_candidates=3,
    )
    summarized_evidence = summarize_evidence(context_pack)

    cfg = getattr(llm_client, "config", None)
    provider = getattr(cfg, "provider", None) or "unknown"
    model = getattr(cfg, "model", None) or "unknown"
    logger.info(
        "graphrag.explanation_generator provider_selected=%s model=%s anomaly_id=%s",
        provider,
        model,
        anomaly_id,
    )

    candidates = context_pack.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        logger.warning(
            "graphrag.explanation_generator fallback reason=no_deterministic_candidates anomaly_id=%s",
            anomaly_id,
        )
        return _finalize_explanation_output(
            _fallback_output(context_pack, summarized_evidence, ["No deterministic RCA candidates for explanation"]),
            context_pack=context_pack,
            unified_investigation_context=unified_investigation_context,
        )

    prompts = build_minimal_deterministic_prompt(context_pack, summarized_evidence)

    logger.info(
        "graphrag.explanation_generator request_attempt anomaly_id=%s provider=%s",
        anomaly_id,
        provider,
    )
    raw = llm_client.generate(
        system_prompt=prompts["system"],
        user_prompt=prompts["user"],
    )
    if not isinstance(raw, dict):
        logger.warning(
            "graphrag.explanation_generator fallback reason=non_object_llm_response anomaly_id=%s",
            anomaly_id,
        )
        return _finalize_explanation_output(
            _fallback_output(context_pack, summarized_evidence, ["LLM returned non-object response"]),
            context_pack=context_pack,
            unified_investigation_context=unified_investigation_context,
        )

    lim = str(raw.get("limitations") or "")
    summary = str(raw.get("explanation_summary") or "")
    if "Provider failure" in lim or "LLM response unavailable" in summary:
        logger.warning(
            "graphrag.explanation_generator fallback reason=provider_or_transport anomaly_id=%s detail=%s",
            anomaly_id,
            lim[:200],
        )
        return _finalize_explanation_output(
            _fallback_output(context_pack, summarized_evidence, [lim or "LLM provider unavailable"]),
            context_pack=context_pack,
            unified_investigation_context=unified_investigation_context,
        )

    merged = _merge_llm_text_into_deterministic_contract(
        raw,
        context_pack=context_pack,
        summarized_evidence=summarized_evidence,
    )

    repaired = validate_or_repair_output(
        merged,
        context_pack=context_pack,
        summarized_evidence=summarized_evidence,
    )
    return _finalize_explanation_output(
        repaired,
        context_pack=context_pack,
        unified_investigation_context=unified_investigation_context,
    )
