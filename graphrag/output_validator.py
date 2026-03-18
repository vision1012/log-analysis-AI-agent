"""Validation, minimal repair, and safe fallback for LLM explanations."""

from __future__ import annotations

from typing import Any, Mapping, Optional

REQUIRED_KEYS = (
    "anomaly_id",
    "primary_candidate",
    "ranked_hypotheses",
    "explanation_summary",
    "evidence_highlights",
    "confidence_alignment_note",
    "optional_patch_direction",
    "limitations",
)

_ABSOLUTE_WORDS = (
    "certain",
    "definitive",
    "guaranteed",
    "proven",
    "without doubt",
    "100%",
)


def _as_float(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _allowed_candidates(context_pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = context_pack.get("candidates") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for c in raw:
        if isinstance(c, dict) and c.get("file_id"):
            out.append(c)
    out.sort(key=lambda c: int(c.get("rank") or 10_000))
    return out


def _safe_fallback(
    *,
    context_pack: Mapping[str, Any],
    errors: list[str],
    summarized_evidence: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    candidates = _allowed_candidates(context_pack)[:3]
    primary = candidates[0] if candidates else {}
    ranked_hypotheses = [
        {
            "rank": c.get("rank"),
            "file_id": c.get("file_id"),
            "path": c.get("path"),
            "confidence": c.get("confidence"),
            "hypothesis": "Deterministic RCA candidate from graph evidence.",
            "evidence_ref": c.get("evidence_ref"),
        }
        for c in candidates
    ]
    highlights: list[str] = []
    if summarized_evidence:
        for b in summarized_evidence:
            t = b.get("text") if isinstance(b, dict) else None
            if isinstance(t, str) and t:
                highlights.append(t)
    if not highlights:
        highlights = ["Explanation fallback used deterministic RCA evidence only."]
    return {
        "anomaly_id": context_pack.get("anomaly_id") or "",
        "primary_candidate": {
            "rank": primary.get("rank", 1),
            "file_id": primary.get("file_id", ""),
            "path": primary.get("path", ""),
            "confidence": primary.get("confidence", 0.0),
            "evidence_ref": primary.get("evidence_ref", ""),
        },
        "ranked_hypotheses": ranked_hypotheses,
        "explanation_summary": "Validated fallback explanation generated from deterministic RCA context.",
        "evidence_highlights": highlights[:8],
        "confidence_alignment_note": "Deterministic ranking remains source of truth.",
        "optional_patch_direction": "Advisory: investigate the top candidate in the latest deterministic run.",
        "limitations": "; ".join(errors[:5]) if errors else "LLM output failed validation.",
    }


def _contains_overstatement(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _ABSOLUTE_WORDS)


def validate_output(
    output: Mapping[str, Any],
    *,
    context_pack: Optional[Mapping[str, Any]] = None,
) -> tuple[bool, list[str]]:
    """Validate explanation shape and deterministic safety constraints."""
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in output:
            errors.append(f"missing key: {key}")

    if "anomaly_id" in output and not isinstance(output.get("anomaly_id"), str):
        errors.append("anomaly_id must be string")
    if context_pack and output.get("anomaly_id") != context_pack.get("anomaly_id"):
        errors.append("anomaly_id mismatch with deterministic context")

    primary = output.get("primary_candidate")
    if not isinstance(primary, Mapping):
        errors.append("primary_candidate must be object")
    ranked = output.get("ranked_hypotheses")
    if not isinstance(ranked, list):
        errors.append("ranked_hypotheses must be list")
        ranked = []

    if "explanation_summary" in output and not isinstance(output.get("explanation_summary"), str):
        errors.append("explanation_summary must be string")
    highlights = output.get("evidence_highlights")
    if not isinstance(highlights, list) or not all(isinstance(x, str) for x in highlights):
        errors.append("evidence_highlights must be list[str]")
    patch = output.get("optional_patch_direction")
    if not isinstance(patch, str):
        errors.append("optional_patch_direction must be string")
    limitations = output.get("limitations")
    if not isinstance(limitations, str):
        errors.append("limitations must be string")

    # Candidate membership and rank-order preservation checks (deterministic source of truth).
    if context_pack:
        deterministic = _allowed_candidates(context_pack)[:3]
        allowed_file_ids = {c.get("file_id") for c in deterministic}
        expected_ranks = [c.get("rank") for c in deterministic]

        if isinstance(primary, Mapping):
            if primary.get("file_id") not in allowed_file_ids:
                errors.append("primary_candidate.file_id is not in allowed deterministic candidates")

        out_ranks: list[Any] = []
        for h in ranked:
            if not isinstance(h, Mapping):
                errors.append("ranked_hypotheses contains non-object item")
                continue
            out_ranks.append(h.get("rank"))
            if h.get("file_id") not in allowed_file_ids:
                errors.append("ranked_hypotheses includes file not present in deterministic candidates")
            conf = _as_float(h.get("confidence"))
            if conf is not None and not (0.0 <= conf <= 1.0):
                errors.append("ranked_hypotheses confidence must be in [0,1]")
        if expected_ranks and out_ranks[: len(expected_ranks)] != expected_ranks[: len(out_ranks)]:
            errors.append("ranked_hypotheses order does not preserve deterministic ranking")

    # Confidence overstatement check.
    summary = output.get("explanation_summary")
    if isinstance(summary, str) and _contains_overstatement(summary):
        errors.append("explanation_summary overstates confidence")
    align = output.get("confidence_alignment_note")
    if isinstance(align, str) and _contains_overstatement(align):
        errors.append("confidence_alignment_note overstates confidence")

    # Advisory patch-direction check.
    if isinstance(patch, str) and patch.strip():
        low = patch.lower()
        if "advisory" not in low and "suggest" not in low and "consider" not in low:
            errors.append("optional_patch_direction must be explicitly advisory")

    return (len(errors) == 0, errors)


def validate_or_repair_output(
    output: Mapping[str, Any],
    *,
    context_pack: Mapping[str, Any],
    summarized_evidence: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Validate generated output and either minimally repair or return safe fallback.

    Minimal repairs:
    - filter unknown candidates
    - restore deterministic rank order
    - clamp numeric confidence values
    - mark patch direction as advisory
    """
    # Start with a mutable copy.
    out = dict(output)

    deterministic = _allowed_candidates(context_pack)[:3]
    allowed_by_file = {c.get("file_id"): c for c in deterministic}
    expected_ranks = [c.get("rank") for c in deterministic]

    ranked = out.get("ranked_hypotheses")
    if isinstance(ranked, list):
        cleaned: list[dict[str, Any]] = []
        for h in ranked:
            if not isinstance(h, Mapping):
                continue
            fid = h.get("file_id")
            if fid not in allowed_by_file:
                continue
            item = dict(h)
            conf = _as_float(item.get("confidence"))
            if conf is not None:
                item["confidence"] = max(0.0, min(1.0, conf))
            cleaned.append(item)
        # Enforce deterministic order.
        cleaned.sort(key=lambda h: expected_ranks.index(h.get("rank")) if h.get("rank") in expected_ranks else 10_000)
        out["ranked_hypotheses"] = cleaned[:3]
    else:
        out["ranked_hypotheses"] = []

    # Ensure primary candidate aligns with deterministic rank 1.
    if deterministic:
        top = deterministic[0]
        out["primary_candidate"] = {
            "rank": top.get("rank", 1),
            "file_id": top.get("file_id", ""),
            "path": top.get("path", ""),
            "confidence": max(0.0, min(1.0, _as_float(top.get("confidence")) or 0.0)),
            "evidence_ref": top.get("evidence_ref", ""),
        }
        out["anomaly_id"] = context_pack.get("anomaly_id") or out.get("anomaly_id") or ""

    # Make patch direction advisory if provided.
    patch = out.get("optional_patch_direction")
    if isinstance(patch, str) and patch.strip():
        low = patch.lower()
        if "advisory" not in low and "suggest" not in low and "consider" not in low:
            out["optional_patch_direction"] = f"Advisory: {patch.strip()}"

    ok, errors = validate_output(out, context_pack=context_pack)
    if ok:
        return out
    return _safe_fallback(
        context_pack=context_pack,
        errors=errors,
        summarized_evidence=summarized_evidence,
    )
