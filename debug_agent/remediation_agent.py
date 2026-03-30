"""Remediation agent: actionable, advisory fixes from deterministic context."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict
from typing import Any, Optional

from debug_agent.langchain_schemas import RemediationLLMOutputSchema, parse_remediation_llm_output
from debug_agent.shared_types import DebugContext, RemediationPackage, StepKind, StepResult
from graphrag.llm_client import GraphRAGLLMClient, LLMConfig

logger = logging.getLogger(__name__)

# Reject advisory text that overstates certainty (aligned with graphrag.output_validator).
_OVERSTATEMENT_WORDS = (
    "certain",
    "definitive",
    "guaranteed",
    "proven",
    "without doubt",
    "100%",
)

MINIMAL_REMEDIATION_SYSTEM_PROMPT = (
    "You suggest next debugging and mitigation steps only. You do NOT determine root cause; "
    "deterministic RCA is authoritative and must not be overridden. "
    "Do not invent code diffs, commits, deployments, incidents, or file paths not implied by the context. "
    "Do not state or imply certainty beyond the given primary_confidence. "
    "Use advisory language (consider, suggest, may). "
    "Output strict JSON with exactly these keys and no others: "
    "remediation_steps (non-empty list of short strings), "
    "reversible_mitigation_suggestions (list of strings), "
    "validation_suggestions (verification / test / monitor steps as strings), "
    "optional_patch_direction (advisory wording only; never present a diff as fact)."
)


def _remediation_llm_enabled() -> bool:
    """Ollama-backed remediation when enabled; off via REMEDIATION_USE_OLLAMA=false."""
    explicit_off = os.getenv("REMEDIATION_USE_OLLAMA", "").strip().lower() in {"0", "false", "no"}
    if explicit_off:
        return False
    if os.getenv("REMEDIATION_USE_OLLAMA", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.getenv("DEBUG_AGENT_REMEDIATION_USE_LLM", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return bool(os.getenv("OLLAMA_HOST", "").strip())


def _rca_candidates(rca_output: dict[str, Any]) -> list[dict[str, Any]]:
    raw = rca_output.get("candidates") if isinstance(rca_output, dict) else []
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


def _deterministic_fallback(
    *,
    anomaly_id: str,
    rca_output: dict[str, Any],
    evidence_output: dict[str, Any],
    memory_output: dict[str, Any],
    explanation_output: dict[str, Any],
    reason: str,
) -> RemediationPackage:
    """Deterministic fallback remediation when LLM is unavailable/fails."""
    candidates = _rca_candidates(rca_output)
    primary = candidates[0] if candidates else {}
    primary_path = primary.get("path") or primary.get("file_id") or "top candidate file"
    top_conf = float(primary.get("confidence") or 0.0)

    service_ref = ""
    if isinstance(memory_output, dict):
        service_ref = str((memory_output.get("metadata") or {}).get("service_ref") or "")

    steps = [
        "Confirm scope and impact using anomaly timeline and service health signals.",
        f"Inspect the top RCA candidate `{primary_path}` and associated recent commits for regressions.",
        "Compare current behavior with last known good deployment and rollback if impact is ongoing.",
        "Apply targeted mitigation (feature flag/guardrail/timeout tuning) and monitor error rate recovery.",
        "After stabilization, capture root-cause notes and add regression coverage to prevent recurrence.",
    ]

    explanation_patch = ""
    if isinstance(explanation_output, dict):
        explanation_patch = str((explanation_output.get("metadata") or {}).get("optional_patch_direction") or "")
    patch_direction = (
        explanation_patch
        if explanation_patch
        else f"Advisory: add defensive handling around `{primary_path}` based on latest failing path and signal evidence."
    )
    if "advisory" not in patch_direction.lower() and "consider" not in patch_direction.lower():
        patch_direction = f"Advisory: {patch_direction}"

    confidence_note = (
        f"Deterministic RCA top confidence={top_conf:.2f}; recommendations are advisory and prioritize reversible mitigations."
        if candidates else
        "No deterministic candidates available; use conservative operational mitigations first."
    )
    if service_ref:
        confidence_note += f" Service context: {service_ref}."
    if reason:
        confidence_note += f" Fallback reason: {reason}"

    return RemediationPackage(
        anomaly_id=anomaly_id,
        steps=steps,
        reversible_mitigation_suggestions=[],
        validation_suggestions=[],
        optional_patch_direction=patch_direction,
        confidence_note=confidence_note,
        metadata={
            "source": "deterministic_fallback",
            "primary_candidate": primary,
            "candidate_count": len(candidates),
            "evidence_refs": [c.get("evidence_ref") for c in candidates if c.get("evidence_ref")],
            "similar_incidents": len(memory_output.get("similar_incidents") or []) if isinstance(memory_output, dict) else 0,
        },
    )


def _text_overstates_confidence(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in _OVERSTATEMENT_WORDS)


def _validate_llm_remediation(
    *,
    llm_out: RemediationLLMOutputSchema,
    allowed_paths: set[str],
    allowed_file_ids: set[str],
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    steps = llm_out.remediation_steps
    if not isinstance(steps, list) or not all(isinstance(x, str) for x in steps):
        errors.append("remediation_steps must be list[str]")
    elif not steps:
        errors.append("remediation_steps must be non-empty")
    rev = llm_out.reversible_mitigation_suggestions
    if not isinstance(rev, list) or not all(isinstance(x, str) for x in rev):
        errors.append("reversible_mitigation_suggestions must be list[str]")
    val = llm_out.validation_suggestions
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        errors.append("validation_suggestions must be list[str]")
    patch = llm_out.optional_patch_direction
    if not isinstance(patch, str):
        errors.append("optional_patch_direction must be string")
    note = llm_out.confidence_note
    if not isinstance(note, str):
        errors.append("confidence_note must be string")

    if isinstance(patch, str):
        lp = patch.lower()
        if "advisory" not in lp and "consider" not in lp and "suggest" not in lp:
            errors.append("optional_patch_direction must be advisory")

    # Conservative file reference check across patch + all suggestion lists:
    # any path-like token should be from deterministic RCA candidates.
    referenced_text = [patch] + [s for s in steps if isinstance(s, str)]
    referenced_text += [s for s in rev if isinstance(s, str)]
    referenced_text += [s for s in val if isinstance(s, str)]
    for text in referenced_text:
        for token in _extract_path_like_tokens(text):
            if allowed_paths and token not in allowed_paths and token not in allowed_file_ids:
                errors.append("LLM remediation references file outside RCA candidates")
                break
        if errors:
            break

    if not errors:
        for text in referenced_text:
            if isinstance(text, str) and text.strip() and _text_overstates_confidence(text):
                errors.append("remediation text overstates confidence")
                break

    return len(errors) == 0, errors


_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+")


def _minimal_remediation_user_payload(
    *,
    anomaly_id: str,
    primary: dict[str, Any],
    evidence_highlights: list[str],
    explanation_summary: str,
) -> str:
    """JSON user message: only deterministic fields (Ollama-grounded)."""
    path = str(primary.get("path") or "").strip()
    fid = str(primary.get("file_id") or "").strip()
    primary_ref = path if path else fid
    payload = {
        "deterministic_context": {
            "anomaly_id": anomaly_id,
            "primary_candidate_file_path": primary_ref,
            "primary_confidence": float(primary.get("confidence") or 0.0),
            "evidence_highlights": evidence_highlights[:12],
            "explanation_summary": (explanation_summary or "")[:4000],
        },
        "output_contract": {
            "json_only": True,
            "required_keys": [
                "remediation_steps",
                "reversible_mitigation_suggestions",
                "validation_suggestions",
                "optional_patch_direction",
            ],
            "must_not_override_rca": True,
            "must_not_invent_diffs_as_facts": True,
            "must_not_claim_root_cause": True,
        },
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _looks_like_llm_client_explanation_fallback(raw: dict[str, Any]) -> bool:
    """GraphRAGLLMClient returns explanation-shaped dict when chat/parse fails."""
    rs = raw.get("remediation_steps")
    if isinstance(rs, list) and len(rs) > 0:
        return False
    lim = str(raw.get("limitations") or "")
    summary = str(raw.get("explanation_summary") or "")
    if "Provider failure" in lim or "LLM response unavailable" in summary:
        return True
    if "primary_candidate" in raw or "ranked_hypotheses" in raw:
        return True
    return False


def _deterministic_confidence_note(primary: dict[str, Any]) -> str:
    conf = float(primary.get("confidence") or 0.0)
    return (
        f"Deterministic RCA top confidence={conf:.2f}. "
        "These items are advisory debugging and mitigation suggestions only; they do not replace graph-ranked RCA."
    )


def _extract_path_like_tokens(text: str) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    out: list[str] = []
    for raw in _PATH_TOKEN_RE.findall(text):
        token = raw.strip("`'\"()[]{}.,:;")
        if token and token not in out:
            out.append(token)
    return out


def _try_llm_assist(
    *,
    anomaly_id: str,
    rca_output: dict[str, Any],
    evidence_output: dict[str, Any],
    memory_output: dict[str, Any],
    explanation_output: dict[str, Any],
) -> Optional[RemediationPackage]:
    """
    Ollama-backed remediation via GraphRAGLLMClient (HTTP /api/chat).

    User message is grounded only in: anomaly_id, primary path/confidence, evidence highlights,
    explanation summary. Memory and multi-candidate lists are not sent to the model.
    confidence_note is always synthesized from deterministic RCA (not LLM output).
    """
    _ = memory_output  # not passed to LLM; still used by deterministic fallback in run()

    if not _remediation_llm_enabled():
        logger.info("debug_agent.remediation_agent.llm_skipped reason=remediation_llm_disabled")
        return None

    cfg = LLMConfig.from_env()
    logger.info(
        "debug_agent.remediation_agent.provider_selected provider=%s model=%s",
        cfg.provider,
        cfg.model,
    )
    if cfg.provider == "stub":
        logger.info("debug_agent.remediation_agent.llm_skipped reason=llm_provider_stub")
        return None

    candidates = _rca_candidates(rca_output)
    if not candidates:
        logger.info("debug_agent.remediation_agent.llm_skipped reason=no_rca_candidates")
        return None
    top_candidates = candidates[:3]
    primary = candidates[0] if candidates else {}
    allowed_paths = {str(c.get("path") or "") for c in top_candidates if c.get("path")}
    allowed_file_ids = {str(c.get("file_id") or "") for c in top_candidates if c.get("file_id")}

    evidence_highlights: list[str] = []
    if isinstance(evidence_output, dict):
        for b in (evidence_output.get("bullets") or [])[:12]:
            if isinstance(b, str) and b:
                evidence_highlights.append(b)

    explanation_summary = ""
    if isinstance(explanation_output, dict):
        explanation_summary = str(explanation_output.get("explanation_summary") or "")

    user_prompt = _minimal_remediation_user_payload(
        anomaly_id=anomaly_id,
        primary=primary,
        evidence_highlights=evidence_highlights,
        explanation_summary=explanation_summary,
    )

    logger.info(
        "debug_agent.remediation_agent.request_attempt anomaly_id=%s provider=%s model=%s",
        anomaly_id,
        cfg.provider,
        cfg.model,
    )

    llm = GraphRAGLLMClient(cfg)
    raw = llm.generate(system_prompt=MINIMAL_REMEDIATION_SYSTEM_PROMPT, user_prompt=user_prompt)

    if not isinstance(raw, dict):
        logger.warning("debug_agent.remediation_agent.llm_fallback reason=non_dict_response")
        return None
    if _looks_like_llm_client_explanation_fallback(raw):
        logger.warning(
            "debug_agent.remediation_agent.llm_fallback reason=provider_or_malformed_transport anomaly_id=%s",
            anomaly_id,
        )
        return None
    if "remediation_steps" not in raw:
        logger.warning("debug_agent.remediation_agent.llm_fallback reason=missing_remediation_steps")
        return None
    parsed = parse_remediation_llm_output(raw)
    if parsed is None:
        logger.warning("debug_agent.remediation_agent.llm_fallback reason=schema_validation_failed")
        return None
    ok, errors = _validate_llm_remediation(
        llm_out=parsed,
        allowed_paths=allowed_paths,
        allowed_file_ids=allowed_file_ids,
    )
    if not ok:
        logger.warning("debug_agent.remediation_agent.llm_fallback reason=validation_failed errors=%s", errors)
        return None

    patch = str(parsed.optional_patch_direction or "")
    if patch and "advisory" not in patch.lower() and "consider" not in patch.lower() and "suggest" not in patch.lower():
        patch = f"Advisory: {patch}"

    conf_note = _deterministic_confidence_note(primary)

    return RemediationPackage(
        anomaly_id=anomaly_id,
        steps=[s for s in parsed.remediation_steps if isinstance(s, str)][:12],
        reversible_mitigation_suggestions=[s for s in parsed.reversible_mitigation_suggestions if isinstance(s, str)][:8],
        validation_suggestions=[s for s in parsed.validation_suggestions if isinstance(s, str)][:8],
        optional_patch_direction=patch,
        confidence_note=conf_note,
        metadata={
            "source": "ollama_assisted",
            "candidate_count": len(top_candidates),
        },
    )


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Generate actionable remediation recommendations.

    Inputs:
    - anomaly_id
    - rca_result
    - evidence_result
    - memory_result
    - explanation_result (optional)
    """
    payload = params or {}
    anomaly_id = str(payload.get("anomaly_id") or context.anomaly_id or "")
    rca_output = payload.get("rca_result") if isinstance(payload.get("rca_result"), dict) else {}
    evidence_output = payload.get("evidence_result") if isinstance(payload.get("evidence_result"), dict) else {}
    memory_output = payload.get("memory_result") if isinstance(payload.get("memory_result"), dict) else {}
    explanation_output = payload.get("explanation_result") if isinstance(payload.get("explanation_result"), dict) else {}

    if not anomaly_id:
        return StepResult(
            step_kind=StepKind.REMEDIATION,
            success=False,
            output={},
            error="missing anomaly_id",
        )

    logger.info("debug_agent.remediation_agent.start anomaly_id=%s", anomaly_id)
    try:
        llm_pkg = _try_llm_assist(
            anomaly_id=anomaly_id,
            rca_output=rca_output,
            evidence_output=evidence_output,
            memory_output=memory_output,
            explanation_output=explanation_output,
        )
        if llm_pkg is not None:
            src = (llm_pkg.metadata or {}).get("source", "llm_assisted")
            logger.info("debug_agent.remediation_agent.done anomaly_id=%s source=%s", anomaly_id, src)
            return StepResult(
                step_kind=StepKind.REMEDIATION,
                success=True,
                output=asdict(llm_pkg),
                error=None,
            )

        pkg = _deterministic_fallback(
            anomaly_id=anomaly_id,
            rca_output=rca_output,
            evidence_output=evidence_output,
            memory_output=memory_output,
            explanation_output=explanation_output,
            reason="LLM disabled or unavailable",
        )
        logger.info(
            "debug_agent.remediation_agent.done anomaly_id=%s source=deterministic_fallback candidate_count=%s",
            anomaly_id,
            len(_rca_candidates(rca_output)),
        )
        return StepResult(
            step_kind=StepKind.REMEDIATION,
            success=True,
            output=asdict(pkg),
            error=None,
        )
    except Exception as exc:
        logger.exception("debug_agent.remediation_agent.error anomaly_id=%s error=%s", anomaly_id, str(exc))
        pkg = _deterministic_fallback(
            anomaly_id=anomaly_id,
            rca_output=rca_output,
            evidence_output=evidence_output,
            memory_output=memory_output,
            explanation_output=explanation_output,
            reason=f"exception: {exc}",
        )
        return StepResult(
            step_kind=StepKind.REMEDIATION,
            success=False,
            output=asdict(pkg),
            error=f"remediation_agent failed: {exc}",
        )
