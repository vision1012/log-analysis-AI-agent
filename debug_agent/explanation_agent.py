"""Explanation agent: generate grounded explanation from active GraphRAG layer."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from typing import Any, Optional

from debug_agent.langchain_schemas import parse_explanation_llm_output
from debug_agent.langchain_utils import invoke_llm, invoke_with_safe_fallback, json_payload, render_prompt
from debug_agent.shared_types import DebugContext, ExplanationPackage, StepKind, StepResult
from debug_agent.tool_registry import invoke
from graphrag.llm_client import GraphRAGLLMClient, LLMConfig

logger = logging.getLogger(__name__)


def _candidates_from_rca_output(rca_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract deterministic candidates from RCAResult-like payload."""
    raw = rca_output.get("candidates") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "rank": int(c.get("rank") or 0),
                "file_id": str(c.get("file_id") or ""),
                "path": str(c.get("path") or ""),
                "confidence": float(c.get("confidence") or 0.0),
                "evidence_ref": str(c.get("evidence_ref") or ""),
            }
        )
    return sorted(out, key=lambda x: (x.get("rank") or 10_000))


def _fallback_from_deterministic(
    anomaly_id: str,
    rca_candidates: list[dict[str, Any]],
    evidence_output: dict[str, Any],
    reason: str,
) -> ExplanationPackage:
    """Safe deterministic fallback when provider/explanation unavailable."""
    top = rca_candidates[0] if rca_candidates else {}
    top_path = top.get("path") or top.get("file_id") or "unknown candidate"
    top_conf = top.get("confidence", 0.0)
    bullets = evidence_output.get("bullets") if isinstance(evidence_output, dict) else []
    highlights = [b for b in bullets if isinstance(b, str)][:8]
    if not highlights:
        highlights = ["Fallback explanation uses deterministic RCA evidence only."]
    return ExplanationPackage(
        anomaly_id=anomaly_id,
        explanation_summary=(
            f"Deterministic RCA indicates {top_path} as the leading candidate."
            if top else
            "No deterministic RCA candidates available for explanation."
        ),
        confidence_alignment_note=(
            f"Reasoning is aligned to deterministic RCA confidence (top={float(top_conf):.2f})."
            if top else
            "No deterministic confidence available."
        ),
        evidence_highlights=highlights,
        limitations=reason,
        metadata={
            "source": "deterministic_fallback",
            "ranked_hypotheses": [
                {
                    "rank": c.get("rank"),
                    "file_id": c.get("file_id"),
                    "path": c.get("path"),
                    "confidence": c.get("confidence"),
                    "evidence_ref": c.get("evidence_ref"),
                }
                for c in rca_candidates[:3]
            ],
            "primary_candidate": top,
        },
    )


def _clamp_ranked_hypotheses_to_deterministic(
    *,
    deterministic_candidates: list[dict[str, Any]],
    ranked_hypotheses: Any,
) -> list[dict[str, Any]]:
    """
    Keep ranked hypotheses grounded to deterministic RCA and deterministic ordering.

    This prevents re-ranking and file invention even when LLM-assist is enabled.
    """
    ranked = ranked_hypotheses if isinstance(ranked_hypotheses, list) else []
    if not deterministic_candidates:
        out: list[dict[str, Any]] = []
        for h in ranked[:3]:
            if not isinstance(h, dict):
                continue
            out.append(
                {
                    "rank": int(h.get("rank") or 0),
                    "file_id": str(h.get("file_id") or ""),
                    "path": str(h.get("path") or ""),
                    "confidence": float(h.get("confidence") or 0.0),
                    "hypothesis": str(h.get("hypothesis") or ""),
                    "evidence_ref": str(h.get("evidence_ref") or ""),
                }
            )
        return out

    by_file: dict[str, dict[str, Any]] = {}
    for h in ranked:
        if isinstance(h, dict):
            fid = str(h.get("file_id") or "")
            if fid and fid not in by_file:
                by_file[fid] = h

    out: list[dict[str, Any]] = []
    for c in deterministic_candidates[:3]:
        fid = str(c.get("file_id") or "")
        src = by_file.get(fid, {})
        out.append(
            {
                "rank": int(c.get("rank") or 0),
                "file_id": fid,
                "path": str(c.get("path") or ""),
                "confidence": float(c.get("confidence") or 0.0),
                "hypothesis": str(src.get("hypothesis") or "Deterministic RCA candidate from graph evidence."),
                "evidence_ref": str(c.get("evidence_ref") or ""),
            }
        )
    return out


def _grounded_highlights(
    *,
    candidate_highlights: Any,
    graphrag_highlights: Any,
    deterministic_bullets: Any,
) -> list[str]:
    """Allow only highlights grounded in GraphRAG/evidence outputs."""
    allowed: list[str] = []
    for line in (graphrag_highlights or []) + (deterministic_bullets or []):
        if isinstance(line, str) and line and line not in allowed:
            allowed.append(line)
    if not allowed:
        return ["Fallback explanation uses deterministic RCA evidence only."]

    proposed = candidate_highlights if isinstance(candidate_highlights, list) else []
    grounded = [x for x in proposed if isinstance(x, str) and x in allowed]
    return grounded[:8] if grounded else allowed[:8]


def _try_llm_assist(
    *,
    anomaly_id: str,
    run_id: Optional[str],
    deterministic_candidates: list[dict[str, Any]],
    graphrag_output: dict[str, Any],
    evidence_output: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Optional LangChain-assisted rewrite constrained by deterministic and GraphRAG context."""
    enabled = os.getenv("DEBUG_AGENT_EXPLANATION_USE_LLM", "false").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return None

    system_prompt = (
        "You format and clarify RCA explanations from deterministic + GraphRAG context only. "
        "Do not re-rank candidates, do not invent files/incidents, and do not alter confidence values. "
        "Return strict JSON with keys: anomaly_id, primary_candidate, ranked_hypotheses, explanation_summary, "
        "evidence_highlights, confidence_alignment_note, optional_patch_direction, limitations."
    )
    payload = {
        "anomaly_id": anomaly_id,
        "run_id": run_id,
        "deterministic_candidates": deterministic_candidates[:3],
        "graphrag_output": graphrag_output,
        "deterministic_evidence_bullets": (evidence_output.get("bullets") if isinstance(evidence_output, dict) else [])[:8],
        "rules": {
            "preserve_deterministic_ordering": True,
            "no_file_invention": True,
            "no_incident_invention": True,
            "confidence_source_of_truth": "deterministic_rca",
        },
    }
    user_prompt = render_prompt("{payload_json}", payload_json=json_payload(payload))
    cfg = LLMConfig.from_env()
    llm = GraphRAGLLMClient(cfg)
    # LangChain path is OpenAI-only; Ollama/stub use GraphRAGLLMClient directly (no spurious primary_failed logs).
    if (cfg.provider or "").strip().lower() == "openai":
        raw = invoke_with_safe_fallback(
            primary_call=lambda: invoke_llm(system_prompt=system_prompt, user_prompt=user_prompt, config=cfg),
            fallback_call=lambda: llm.generate(system_prompt=system_prompt, user_prompt=user_prompt),
            context="explanation_agent",
        )
    else:
        raw = llm.generate(system_prompt=system_prompt, user_prompt=user_prompt)
    if not isinstance(raw, dict):
        return None
    parsed = parse_explanation_llm_output(raw)
    if parsed is None:
        return None
    if str(parsed.anomaly_id or anomaly_id) != anomaly_id:
        return None

    primary = parsed.primary_candidate.model_dump()
    allowed_file_ids = {str(c.get("file_id") or "") for c in deterministic_candidates if isinstance(c, dict)}
    if primary and allowed_file_ids and str(primary.get("file_id") or "") not in allowed_file_ids:
        return None

    ranked = _clamp_ranked_hypotheses_to_deterministic(
        deterministic_candidates=deterministic_candidates,
        ranked_hypotheses=[h.model_dump() for h in parsed.ranked_hypotheses],
    )
    top = deterministic_candidates[0] if deterministic_candidates else primary
    return {
        "anomaly_id": anomaly_id,
        "primary_candidate": top if isinstance(top, dict) else {},
        "ranked_hypotheses": ranked,
        "explanation_summary": str(parsed.explanation_summary or graphrag_output.get("explanation_summary") or ""),
        "evidence_highlights": _grounded_highlights(
            candidate_highlights=parsed.evidence_highlights,
            graphrag_highlights=graphrag_output.get("evidence_highlights"),
            deterministic_bullets=evidence_output.get("bullets") if isinstance(evidence_output, dict) else [],
        ),
        "confidence_alignment_note": str(
            parsed.confidence_alignment_note
            or graphrag_output.get("confidence_alignment_note")
            or "Deterministic ranking and confidence remain the source of truth."
        ),
        "optional_patch_direction": str(parsed.optional_patch_direction or graphrag_output.get("optional_patch_direction") or ""),
        "limitations": str(parsed.limitations or graphrag_output.get("limitations") or ""),
    }


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run explanation step using active GraphRAG modules.

    Inputs:
    - anomaly_id
    - optional RCA output (params["rca_result"])
    - optional Evidence output (params["evidence_result"])
    """
    payload = params or {}
    anomaly_id = str(payload.get("anomaly_id") or context.anomaly_id or "")
    rca_output = payload.get("rca_result") if isinstance(payload.get("rca_result"), dict) else {}
    evidence_output = payload.get("evidence_result") if isinstance(payload.get("evidence_result"), dict) else {}
    run_id = payload.get("run_id") or rca_output.get("run_id") or context.run_id

    if not anomaly_id:
        return StepResult(
            step_kind=StepKind.EXPLANATION,
            success=False,
            output={},
            error="missing anomaly_id",
        )

    logger.info(
        "debug_agent.explanation_agent.start anomaly_id=%s run_id=%s",
        anomaly_id,
        run_id,
    )

    deterministic_candidates = _candidates_from_rca_output(rca_output)

    try:
        # Active GraphRAG service wrapper (preserves existing validator/fallback behavior).
        explanation = invoke("get_graphrag_explanation", anomaly_id, run_id=run_id)
        if not isinstance(explanation, dict):
            pkg = _fallback_from_deterministic(
                anomaly_id,
                deterministic_candidates,
                evidence_output,
                "GraphRAG returned non-object output.",
            )
            return StepResult(
                step_kind=StepKind.EXPLANATION,
                success=False,
                output=asdict(pkg),
                error="non-object GraphRAG output",
            )

        source = "graphrag"
        graphrag_highlights = explanation.get("evidence_highlights")
        llm_refined = _try_llm_assist(
            anomaly_id=anomaly_id,
            run_id=run_id,
            deterministic_candidates=deterministic_candidates,
            graphrag_output=explanation,
            evidence_output=evidence_output,
        )
        if isinstance(llm_refined, dict):
            explanation = llm_refined
            source = "llm_assisted"

        ranked_hypotheses = _clamp_ranked_hypotheses_to_deterministic(
            deterministic_candidates=deterministic_candidates,
            ranked_hypotheses=explanation.get("ranked_hypotheses"),
        )

        ev_highlights = _grounded_highlights(
            candidate_highlights=explanation.get("evidence_highlights"),
            graphrag_highlights=graphrag_highlights,
            deterministic_bullets=evidence_output.get("bullets") if isinstance(evidence_output, dict) else [],
        )

        pkg = ExplanationPackage(
            anomaly_id=anomaly_id,
            explanation_summary=str(explanation.get("explanation_summary") or ""),
            confidence_alignment_note=str(explanation.get("confidence_alignment_note") or ""),
            evidence_highlights=ev_highlights[:8],
            limitations=str(
                explanation.get("limitations")
                or explanation.get("limitations_or_uncertainty")
                or ""
            ),
            metadata={
                "source": source,
                "primary_candidate": (
                    deterministic_candidates[0] if deterministic_candidates else (explanation.get("primary_candidate") or {})
                ),
                "ranked_hypotheses": ranked_hypotheses[:3],
                "optional_patch_direction": str(explanation.get("optional_patch_direction") or ""),
                "run_id": run_id,
            },
        )
        logger.info(
            "debug_agent.explanation_agent.done anomaly_id=%s hypotheses=%s",
            anomaly_id,
            len(ranked_hypotheses),
        )
        return StepResult(
            step_kind=StepKind.EXPLANATION,
            success=True,
            output=asdict(pkg),
            error=None,
        )
    except Exception as exc:
        logger.exception(
            "debug_agent.explanation_agent.error anomaly_id=%s run_id=%s error=%s",
            anomaly_id,
            run_id,
            str(exc),
        )
        pkg = _fallback_from_deterministic(
            anomaly_id,
            deterministic_candidates,
            evidence_output,
            f"GraphRAG unavailable: {exc}",
        )
        return StepResult(
            step_kind=StepKind.EXPLANATION,
            success=False,
            output=asdict(pkg),
            error=f"explanation_agent failed: {exc}",
        )
