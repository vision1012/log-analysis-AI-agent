"""Remediation agent: actionable, advisory fixes from deterministic context."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from typing import Any, Optional

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
    llm_out: dict[str, Any],
    allowed_paths: set[str],
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    steps = llm_out.get("remediation_steps")
    if not isinstance(steps, list) or not all(isinstance(x, str) for x in steps):
        errors.append("remediation_steps must be list[str]")
    patch = llm_out.get("optional_patch_direction")
    if not isinstance(patch, str):
        errors.append("optional_patch_direction must be string")
    note = llm_out.get("confidence_note")
    if not isinstance(note, str):
        errors.append("confidence_note must be string")

    if isinstance(patch, str):
        lp = patch.lower()
        if "advisory" not in lp and "consider" not in lp and "suggest" not in lp:
            errors.append("optional_patch_direction must be advisory")
        # Conservative file reference check: if it references a repo path-like token,
        # it must belong to deterministic candidate paths.
        for token in patch.replace(",", " ").split():
            if "/" in token and "." in token:
                candidate_token = token.strip("`'\"()[]{}")
                if allowed_paths and candidate_token not in allowed_paths:
                    errors.append("optional_patch_direction references file outside RCA candidates")
                    break

    return len(errors) == 0, errors


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
    user_prompt = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    llm = GraphRAGLLMClient(LLMConfig.from_env())
    raw = llm.generate(system_prompt=system_prompt, user_prompt=user_prompt)
    if not isinstance(raw, dict):
        return None
    ok, errors = _validate_llm_remediation(llm_out=raw, allowed_paths=allowed_paths)
    if not ok:
        logger.warning("debug_agent.remediation_agent.llm_invalid errors=%s", errors)
        return None

    patch = str(raw.get("optional_patch_direction") or "")
    if patch and "advisory" not in patch.lower() and "consider" not in patch.lower():
        patch = f"Advisory: {patch}"

    return RemediationPackage(
        anomaly_id=anomaly_id,
        steps=[s for s in (raw.get("remediation_steps") or []) if isinstance(s, str)][:10],
        optional_patch_direction=patch,
        confidence_note=str(raw.get("confidence_note") or ""),
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
        logger.info("debug_agent.remediation_agent.done anomaly_id=%s source=deterministic_fallback", anomaly_id)
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
