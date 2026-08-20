"""Validation, minimal repair, and safe fallback for LLM explanations."""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

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

# Extremely short summaries fail quality gates and fall back to deterministic text.
_MIN_EXPLANATION_CHARS = 120
_MIN_EXPLANATION_WORDS = 40

_PATH_LIKE_RE = re.compile(
    r"(?:(?:[A-Za-z]:)?(?:/|\\)[\w.\-]+(?:/(?:[\w.\-]+))+|(?:[\w.\-]+/){2,}[\w.\-]+\.[\w]+)"
)
_CONFIDENCE_RE = re.compile(
    r"\bconfidence(?:\s+(?:score|of|is|at))?\s*[:=]?\s*(0?\.\d+|1(?:\.0+)?|\d{1,3}%)\b",
    re.IGNORECASE,
)
_RERANK_PHRASES = (
    "instead the root cause is",
    "actual root cause is",
    "more likely root cause",
    "rerank",
    "re-rank",
    "should be ranked first",
    "true root cause is",
)


def _as_float(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _parse_confidence_token(token: str) -> Optional[float]:
    raw = token.strip()
    if raw.endswith("%"):
        try:
            return float(raw[:-1]) / 100.0
        except ValueError:
            return None
    return _as_float(raw)


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


def _context_corpus(context_pack: Mapping[str, Any], *, limit: int = 400) -> str:
    """Flatten context strings for grounded entity membership checks."""
    chunks: list[str] = []

    def _walk(value: Any, depth: int = 0) -> None:
        if len(chunks) >= limit or depth > 6:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                chunks.append(text.lower())
            return
        if isinstance(value, Mapping):
            for item in value.values():
                _walk(item, depth + 1)
            return
        if isinstance(value, list):
            for item in value[:50]:
                _walk(item, depth + 1)

    _walk(context_pack)
    return "\n".join(chunks)


def _allowed_entity_tokens(context_pack: Mapping[str, Any]) -> set[str]:
    """Collect normalized path/id tokens that may appear in a grounded explanation."""
    tokens: set[str] = set()

    def _add(value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        tokens.add(text.lower())
        tokens.add(text.lower().replace("\\", "/"))
        base = text.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base:
            tokens.add(base)

    for c in _allowed_candidates(context_pack):
        _add(c.get("path"))
        _add(c.get("file_id"))
        cde = c.get("commit_deployment_evidence") or {}
        if isinstance(cde, Mapping):
            _add(cde.get("last_touch_commit_sha"))
            _add(cde.get("deployment_id"))

    jira = context_pack.get("jira_ticket_context") or {}
    if isinstance(jira, Mapping):
        _add(jira.get("issue_key"))

    inv = context_pack.get("investigation_context") or {}
    if isinstance(inv, Mapping):
        for key in (
            "related_deployments",
            "related_alerts",
            "related_incidents",
            "recent_commits",
            "previous_investigations",
        ):
            for item in inv.get(key) or []:
                if not isinstance(item, Mapping):
                    continue
                for field in ("id", "name", "sha", "investigation_id", "ticket_key", "path"):
                    _add(item.get(field))

    similar = context_pack.get("similar_incident_context") or {}
    if isinstance(similar, Mapping):
        for item in similar.get("previous_investigation_summaries") or []:
            if isinstance(item, Mapping):
                _add(item.get("investigation_id"))

    # Also harvest path-like tokens already present anywhere in packed context.
    for match in _PATH_LIKE_RE.finditer(_context_corpus(context_pack)):
        _add(match.group(0))

    return tokens


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
    path = str(primary.get("path") or primary.get("file_id") or "the top candidate")
    confidence = primary.get("confidence", 0.0)
    try:
        conf_txt = f"{float(confidence):.2f}"
    except (TypeError, ValueError):
        conf_txt = str(confidence)
    evidence_note = highlights[0] if highlights else "deterministic graph and evidence context"
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
        "explanation_summary": (
            f"Validated fallback explanation generated from deterministic RCA context. "
            f"The engine ranked `{path}` as the leading root-cause candidate "
            f"(confidence {conf_txt}). "
            f"Supporting evidence includes: {evidence_note}. "
            "Inspect this candidate around the failing execution path and recent related changes. "
            "This assistive summary does not replace or re-rank the deterministic RCA result."
        ),
        "evidence_highlights": highlights[:8],
        "confidence_alignment_note": "Deterministic ranking remains source of truth.",
        "optional_patch_direction": "Advisory: investigate the top candidate in the latest deterministic run.",
        "limitations": "; ".join(errors[:5]) if errors else "LLM output failed validation.",
    }


def _contains_overstatement(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _ABSOLUTE_WORDS)


def _validate_explanation_quality(
    summary: str,
    *,
    context_pack: Optional[Mapping[str, Any]],
) -> list[str]:
    errors: list[str] = []
    text = summary.strip()
    if not text:
        errors.append("explanation_summary is empty")
        return errors
    if len(text) < _MIN_EXPLANATION_CHARS or _word_count(text) < _MIN_EXPLANATION_WORDS:
        errors.append("explanation_summary is extremely short")

    lowered = text.lower()
    if any(phrase in lowered for phrase in _RERANK_PHRASES):
        errors.append("explanation_summary attempts to rerank or replace the selected candidate")

    if not context_pack:
        return errors

    deterministic = _allowed_candidates(context_pack)
    top = deterministic[0] if deterministic else {}
    top_path = str(top.get("path") or "").strip()
    top_conf = _as_float(top.get("confidence"))

    if top_path:
        path_norm = top_path.replace("\\", "/").lower()
        basename = path_norm.rsplit("/", 1)[-1]
        if path_norm not in lowered and basename not in lowered:
            other_named = False
            for c in deterministic[1:]:
                other = str(c.get("path") or "").strip().replace("\\", "/").lower()
                other_base = other.rsplit("/", 1)[-1] if other else ""
                if other and (other in lowered or (other_base and other_base in lowered)):
                    other_named = True
                    break
            if other_named:
                errors.append("explanation_summary contradicts the selected RCA candidate")

    if top_conf is not None:
        for match in _CONFIDENCE_RE.finditer(text):
            parsed = _parse_confidence_token(match.group(1))
            if parsed is None:
                continue
            if abs(parsed - top_conf) > 0.02:
                errors.append("explanation_summary includes a different confidence score")
                break

    allowed = _allowed_entity_tokens(context_pack)
    corpus = _context_corpus(context_pack)
    if allowed or corpus:
        for match in _PATH_LIKE_RE.finditer(text):
            token = match.group(0).strip().lower().replace("\\", "/")
            base = token.rsplit("/", 1)[-1]
            if token in allowed or base in allowed or token in corpus or base in corpus:
                continue
            if token.count("/") < 1 and "\\" not in match.group(0):
                continue
            errors.append("explanation_summary mentions entities not present in deterministic context")
            break

    return errors


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
            top_det = deterministic[0] if deterministic else None
            if isinstance(top_det, Mapping):
                det_path = str(top_det.get("path") or "").strip()
                out_path = str(primary.get("path") or "").strip()
                if det_path and out_path and out_path != det_path:
                    errors.append("primary_candidate.path does not match deterministic RCA top candidate")
                det_conf = _as_float(top_det.get("confidence"))
                out_conf = _as_float(primary.get("confidence"))
                if det_conf is not None and out_conf is not None and abs(det_conf - out_conf) > 0.001:
                    errors.append("primary_candidate.confidence does not match deterministic confidence")

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

    if isinstance(summary, str):
        errors.extend(_validate_explanation_quality(summary, context_pack=context_pack))

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
    logger.warning("graphrag.validate_or_repair_output fallback_triggered errors=%s", errors)
    return _safe_fallback(
        context_pack=context_pack,
        errors=errors,
        summarized_evidence=summarized_evidence,
    )
