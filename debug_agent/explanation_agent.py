"""Explanation agent: generate grounded explanation from active GraphRAG layer."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from debug_agent.shared_types import DebugContext, ExplanationPackage, StepKind, StepResult
from debug_agent.tool_registry import invoke

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

        ranked_hypotheses = explanation.get("ranked_hypotheses") or []
        if not isinstance(ranked_hypotheses, list):
            ranked_hypotheses = []

        # Safety clamp to deterministic RCA candidate set when provided.
        if deterministic_candidates:
            allowed = {c.get("file_id") for c in deterministic_candidates}
            ranked_hypotheses = [
                h for h in ranked_hypotheses
                if isinstance(h, dict) and h.get("file_id") in allowed
            ]

        ev_highlights = explanation.get("evidence_highlights") or []
        if not isinstance(ev_highlights, list):
            ev_highlights = []
        ev_highlights = [x for x in ev_highlights if isinstance(x, str)]
        if not ev_highlights:
            # Fall back to deterministic evidence bullets.
            bullets = evidence_output.get("bullets") if isinstance(evidence_output, dict) else []
            ev_highlights = [b for b in bullets if isinstance(b, str)][:8]

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
                "source": "graphrag",
                "primary_candidate": explanation.get("primary_candidate") or {},
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
