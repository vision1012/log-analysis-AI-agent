"""Remediation agent: actionable, advisory fixes from deterministic context."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict
from typing import Any, Optional

from debug_agent.langchain_schemas import RemediationLLMOutputSchema, parse_remediation_llm_output
from debug_agent.langchain_utils import invoke_llm, invoke_with_safe_fallback, json_payload, render_prompt
from debug_agent.shared_types import DebugContext, RemediationPackage, StepKind, StepResult
from graphrag.llm_client import GraphRAGLLMClient, LLMConfig

logger = logging.getLogger(__name__)


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

    # Conservative file reference check across patch + remediation steps:
    # any path-like token should be from deterministic RCA candidates.
    referenced_text = [patch] + [s for s in steps if isinstance(s, str)]
    for text in referenced_text:
        for token in _extract_path_like_tokens(text):
            if allowed_paths and token not in allowed_paths and token not in allowed_file_ids:
                errors.append("LLM remediation references file outside RCA candidates")
                break
        if errors:
            break

    return len(errors) == 0, errors


_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+")


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
    """Optional LLM-assisted remediation synthesis with strict grounding."""
    use_llm = os.getenv("DEBUG_AGENT_REMEDIATION_USE_LLM", "false").strip().lower() in {"1", "true", "yes"}
    if not use_llm:
        return None

    candidates = _rca_candidates(rca_output)
    top_candidates = candidates[:3]
    allowed_paths = {str(c.get("path") or "") for c in top_candidates if c.get("path")}
    allowed_file_ids = {str(c.get("file_id") or "") for c in top_candidates if c.get("file_id")}
    logger.info(
        "debug_agent.remediation_agent.llm_attempt anomaly_id=%s candidates=%s",
        anomaly_id,
        len(top_candidates),
    )

    system_prompt = (
        "You are a remediation assistant. Use only provided deterministic RCA/evidence context. "
        "Do not invent files or override RCA ranking. "
        "Output strict JSON with keys: remediation_steps (list of actionable strings), "
        "optional_patch_direction (advisory string), confidence_note (string)."
    )
    payload = {
        "anomaly_id": anomaly_id,
        "top_candidates": top_candidates,
        "evidence_bullets": (evidence_output.get("bullets") if isinstance(evidence_output, dict) else [])[:8],
        "memory_summary": {
            "similar_incidents": (memory_output.get("similar_incidents") if isinstance(memory_output, dict) else [])[:5],
            "recurrence_score": (memory_output.get("recurrence_score") if isinstance(memory_output, dict) else 0.0),
            "historical_patterns_summary": (
                memory_output.get("historical_patterns_summary") if isinstance(memory_output, dict) else ""
            ),
        },
        "explanation_summary": (
            explanation_output.get("explanation_summary") if isinstance(explanation_output, dict) else ""
        ),
        "rules": {
            "must_be_advisory": True,
            "must_not_invent_files": True,
            "must_not_override_rca": True,
            "must_be_actionable": True,
        },
    }
    user_prompt = render_prompt("{payload_json}", payload_json=json_payload(payload))
    cfg = LLMConfig.from_env()
    llm = GraphRAGLLMClient(cfg)
    raw = invoke_with_safe_fallback(
        primary_call=lambda: invoke_llm(system_prompt=system_prompt, user_prompt=user_prompt, config=cfg),
        fallback_call=lambda: llm.generate(system_prompt=system_prompt, user_prompt=user_prompt),
        context="remediation_agent",
    )
    if not isinstance(raw, dict):
        return None
    parsed = parse_remediation_llm_output(raw)
    if parsed is None:
        logger.warning("debug_agent.remediation_agent.llm_invalid errors=%s", ["schema validation failed"])
        return None
    ok, errors = _validate_llm_remediation(
        llm_out=parsed,
        allowed_paths=allowed_paths,
        allowed_file_ids=allowed_file_ids,
    )
    if not ok:
        logger.warning("debug_agent.remediation_agent.llm_invalid errors=%s", errors)
        return None

    patch = str(parsed.optional_patch_direction or "")
    if patch and "advisory" not in patch.lower() and "consider" not in patch.lower():
        patch = f"Advisory: {patch}"

    return RemediationPackage(
        anomaly_id=anomaly_id,
        steps=[s for s in parsed.remediation_steps if isinstance(s, str)][:10],
        optional_patch_direction=patch,
        confidence_note=str(parsed.confidence_note or ""),
        metadata={
            "source": "llm_assisted",
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
            logger.info("debug_agent.remediation_agent.done anomaly_id=%s source=llm_assisted", anomaly_id)
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
