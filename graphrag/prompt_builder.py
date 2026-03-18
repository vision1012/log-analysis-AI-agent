"""Build concise, guardrailed prompts for graph-grounded RCA explanations."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional


SYSTEM_PROMPT = (
    "You are an RCA explanation assistant. Use only the provided deterministic graph context. "
    "Do not invent files, candidates, commits, deployments, or evidence. "
    "Do not re-rank candidates; deterministic ranking is the source of truth. "
    "Explain why the top candidate is most likely, summarize top-3 ranked hypotheses, "
    "align reasoning with provided confidence values, and provide optional advisory-only patch direction. "
    "If evidence is incomplete, explicitly state uncertainty. "
    "Output must be strict JSON only."
)


def _extract_ranked_candidates(context_pack: Mapping[str, Any], max_candidates: int) -> list[dict[str, Any]]:
    raw = context_pack.get("candidates") or []
    if not isinstance(raw, list):
        return []
    ranked = [c for c in raw if isinstance(c, Mapping)]
    ranked.sort(key=lambda c: int(c.get("rank") or 10_000))
    out: list[dict[str, Any]] = []
    for c in ranked[:max_candidates]:
        out.append(
            {
                "rank": c.get("rank"),
                "file_id": c.get("file_id"),
                "path": c.get("path"),
                "confidence": c.get("confidence"),
                "evidence_ref": c.get("evidence_ref"),
            }
        )
    return out


def build_prompt(
    context_pack: Mapping[str, Any],
    summarized_evidence: list[Mapping[str, Any]] | list[str],
    *,
    user_instruction: Optional[str] = None,
    max_hypotheses: int = 3,
) -> dict[str, str]:
    """
    Build system/user prompt strings for LLM explanation generation.

    Prompt objectives:
    - explain top deterministic candidate
    - summarize top-3 ranked hypotheses (without re-ranking)
    - provide confidence-aligned reasoning
    - include optional advisory-only patch direction
    """
    instruction = user_instruction or (
        "Explain the deterministic RCA outcome using only provided evidence."
    )
    ranked_candidates = _extract_ranked_candidates(context_pack, max_hypotheses)
    primary = ranked_candidates[0] if ranked_candidates else {}
    payload = {
        "task": instruction,
        "rules": {
            "must_not_rerank": True,
            "must_not_introduce_new_candidates": True,
            "deterministic_ranking_source_of_truth": True,
            "patch_direction_must_be_advisory": True,
            "no_full_proprietary_code_or_raw_logs": True,
        },
        "required_response_fields": [
            "anomaly_id",
            "primary_candidate",
            "ranked_hypotheses",
            "explanation_summary",
            "evidence_highlights",
            "confidence_alignment_note",
            "optional_patch_direction",
            "limitations",
        ],
        "response_constraints": {
            "ranked_hypotheses_max": max_hypotheses,
            "ranked_hypotheses_must_match_input_order": True,
            "json_only": True,
        },
        "context": {
            "anomaly_id": context_pack.get("anomaly_id"),
            "trace_ref": context_pack.get("trace_ref"),
            "run_id": context_pack.get("run_id"),
            "top_ranked_candidates": ranked_candidates,
            "primary_candidate_hint": primary,
            "packed_context": context_pack,
            "summarized_evidence": summarized_evidence,
        },
    }
    return {
        "system": SYSTEM_PROMPT,
        "user": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
    }
