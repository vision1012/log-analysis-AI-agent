"""Build concise, guardrailed prompts for graph-grounded RCA explanations."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

MINIMAL_DETERMINISTIC_SYSTEM_PROMPT = (
    "You are an RCA explanation assistant. You receive ONLY the deterministic JSON block "
    "under deterministic_context. Do not invent files, commits, deployments, incidents, or candidates. "
    "Do not re-rank or change confidence. "
    "Write an assistive narrative that explains the top candidate in plain language. "
    "Output strict JSON only, with exactly these keys and no others: "
    "explanation_summary, evidence_highlights, confidence_alignment_note, optional_patch_direction, limitations. "
    "evidence_highlights must be a list of strings; each string must be copied verbatim from "
    "deterministic_context.evidence_highlights or be a short paraphrase that does not add new facts. "
    "optional_patch_direction must be advisory (use words like advisory, consider, or suggest). "
    "If context is insufficient, say so in limitations."
)


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


def _evidence_bullet_strings(summarized_evidence: list[Mapping[str, Any]] | list[str]) -> list[str]:
    out: list[str] = []
    for item in summarized_evidence:
        if isinstance(item, Mapping):
            t = item.get("text")
        elif isinstance(item, str):
            t = item
        else:
            t = None
        if isinstance(t, str) and t.strip() and t not in out:
            out.append(t)
    return out


def build_minimal_deterministic_prompt(
    context_pack: Mapping[str, Any],
    summarized_evidence: list[Mapping[str, Any]] | list[str],
) -> dict[str, str]:
    """
    Ollama/local-LLM prompt: user message contains only deterministic fields.

    Included: anomaly_id, primary file path, primary confidence, evidence highlight strings,
    limitations_context (optional operator note; empty if none).
    """
    ranked = _extract_ranked_candidates(context_pack, max_candidates=3)
    primary = ranked[0] if ranked else {}
    primary_path = str(primary.get("path") or "")
    primary_confidence = float(primary.get("confidence") or 0.0)
    bullets = _evidence_bullet_strings(summarized_evidence)
    limitations_context = str(context_pack.get("limitations_context") or "").strip()

    payload = {
        "deterministic_context": {
            "anomaly_id": context_pack.get("anomaly_id"),
            "primary_candidate_file_path": primary_path,
            "primary_confidence": primary_confidence,
            "evidence_highlights": bullets[:12],
            "limitations_context": limitations_context,
        },
        "output_contract": {
            "json_only": True,
            "required_keys": [
                "explanation_summary",
                "evidence_highlights",
                "confidence_alignment_note",
                "optional_patch_direction",
                "limitations",
            ],
            "must_not_invent_entities": True,
            "must_not_rerank": True,
            "patch_direction_advisory_only": True,
        },
    }
    return {
        "system": MINIMAL_DETERMINISTIC_SYSTEM_PROMPT,
        "user": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
    }
