"""Orchestrate GraphRAG explanation generation from RCA outputs."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from graphrag.context_packer import pack_context
from graphrag.evidence_summarizer import summarize_evidence
from graphrag.output_validator import validate_output
from graphrag.prompt_builder import build_prompt


def _fallback_output(
    anomaly_id: str,
    bullets: list[str],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "summary": f"Could not generate a validated LLM explanation for anomaly {anomaly_id}.",
        "primary_cause_file_id": "",
        "confidence": 0.0,
        "evidence_bullets": bullets[:6] or ["No evidence bullets available."],
        "limitations": ["Validation failed."] + errors[:4],
    }


def generate_explanation(
    anomaly_id: str,
    *,
    result_view: Mapping[str, Any],
    llm_client: Any,
    run_summary: Optional[Mapping[str, Any]] = None,
    evidence_bundles: Optional[Mapping[str, Mapping[str, Any]]] = None,
    user_instruction: Optional[str] = None,
) -> dict[str, Any]:
    """
    Generate a guardrailed explanation payload.

    Returns a dict that follows graphrag/specs/explanation_output_contract.md.
    """
    context_pack = pack_context(
        anomaly_id,
        result_view=result_view,
        run_summary=run_summary,
        evidence_bundles=evidence_bundles,
    )
    bullets = summarize_evidence(context_pack)
    prompts = build_prompt(context_pack, bullets, user_instruction=user_instruction)

    raw = llm_client.generate(
        system_prompt=prompts["system"],
        user_prompt=prompts["user"],
    )
    ok, errors = validate_output(raw)
    if not ok:
        return _fallback_output(anomaly_id, bullets, errors)
    return dict(raw)
