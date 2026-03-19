"""Orchestrate deterministic RCA explanation generation for GraphRAG."""

from __future__ import annotations

from typing import Any, Optional

from artifacts.evidence_store import EvidenceStore
from graph.neo4j_client import Neo4jClient
from graphrag.context_packer import pack_context
from graphrag.evidence_summarizer import summarize_evidence
from graphrag.output_validator import validate_or_repair_output
from graphrag.prompt_builder import build_prompt


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
) -> dict[str, Any]:
    """
    Generate explanation for the latest deterministic RCA run (or provided run_id).

    Pipeline:
      1) pack context
      2) summarize evidence
      3) build prompt
      4) call LLM
      5) validate output
    """
    context_pack = pack_context(
        anomaly_id,
        graph_client=graph_client,
        evidence_store=evidence_store,
        run_id=run_id,
        max_candidates=3,
    )
    summarized_evidence = summarize_evidence(context_pack)
    prompts = build_prompt(
        context_pack,
        summarized_evidence,
        user_instruction=user_instruction,
        max_hypotheses=3,
    )

    raw = llm_client.generate(
        system_prompt=prompts["system"],
        user_prompt=prompts["user"],
    )
    if not isinstance(raw, dict):
        return _fallback_output(context_pack, summarized_evidence, ["LLM returned non-object response"])

    repaired = validate_or_repair_output(
        raw,
        context_pack=context_pack,
        summarized_evidence=summarized_evidence,
    )
    return repaired
