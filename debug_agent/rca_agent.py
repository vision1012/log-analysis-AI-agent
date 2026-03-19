"""RCA agent: run deterministic RCA and normalize output."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from api.services.rca_service import get_rca_results, run_rca
from debug_agent.shared_types import DebugContext, RCAResult, RootCauseCandidate, StepKind, StepResult

logger = logging.getLogger(__name__)


def _normalize_candidates(rows: list[dict[str, Any]]) -> list[RootCauseCandidate]:
    """Convert raw RCA rows to shared RootCauseCandidate objects without re-ranking."""
    out: list[RootCauseCandidate] = []
    for idx, row in enumerate(rows, start=1):
        out.append(
            RootCauseCandidate(
                rank=idx,
                file_id=str(row.get("file_id") or ""),
                path=str(row.get("path") or ""),
                confidence=float(row.get("confidence") or 0.0),
                evidence_ref=str(row.get("evidence_ref") or ""),
            )
        )
    return out


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run deterministic RCA and return normalized RCAResult.

    Source of truth:
    - deterministic RCA runner and persisted RCA_ATTRIBUTED results.
    """
    payload = params or {}
    anomaly_id = str(payload.get("anomaly_id") or context.anomaly_id or "")
    run_id = payload.get("run_id") or context.run_id
    override = bool(payload.get("override", False))

    if not anomaly_id:
        return StepResult(
            step_kind=StepKind.RCA,
            success=False,
            output={},
            error="missing anomaly_id",
        )

    logger.info(
        "debug_agent.rca_agent.start anomaly_id=%s run_id=%s override=%s",
        anomaly_id,
        run_id,
        override,
    )

    try:
        run_summary = run_rca(
            anomaly_id,
            trigger_type="manual",
            run_id=run_id,
            override=override,
        )

        rows = get_rca_results(anomaly_id)
        candidates = _normalize_candidates(rows)
        primary = candidates[0] if candidates else None

        if run_summary is None and not candidates:
            rca_result = RCAResult(
                anomaly_id=anomaly_id,
                run_id=run_id,
                candidates=[],
                primary=None,
                metadata={
                    "rca_status": "no_candidates",
                    "attribution_count": 0,
                    "evidence_refs": [],
                },
            )
            logger.warning(
                "debug_agent.rca_agent.no_candidates anomaly_id=%s run_id=%s",
                anomaly_id,
                run_id,
            )
            return StepResult(
                step_kind=StepKind.RCA,
                success=False,
                output=asdict(rca_result),
                error="deterministic RCA returned no candidates",
            )

        resolved_run_id = (run_summary or {}).get("run_id") or run_id
        evidence_refs = [c.evidence_ref for c in candidates if c.evidence_ref]

        rca_result = RCAResult(
            anomaly_id=anomaly_id,
            run_id=resolved_run_id,
            candidates=candidates,
            primary=primary,
            metadata={
                "rca_status": "completed" if candidates else "blocked",
                "attribution_count": len(candidates),
                "evidence_refs": evidence_refs,
            },
        )
        logger.info(
            "debug_agent.rca_agent.done anomaly_id=%s run_id=%s candidates=%s",
            anomaly_id,
            resolved_run_id,
            len(candidates),
        )
        return StepResult(
            step_kind=StepKind.RCA,
            success=bool(candidates),
            output=asdict(rca_result),
            error=None if candidates else "no RCA candidates found",
        )
    except Exception as exc:
        logger.exception(
            "debug_agent.rca_agent.error anomaly_id=%s run_id=%s error=%s",
            anomaly_id,
            run_id,
            str(exc),
        )
        fallback = RCAResult(
            anomaly_id=anomaly_id,
            run_id=run_id,
            candidates=[],
            primary=None,
            metadata={
                "rca_status": "failed",
                "attribution_count": 0,
                "evidence_refs": [],
            },
        )
        return StepResult(
            step_kind=StepKind.RCA,
            success=False,
            output=asdict(fallback),
            error=f"rca_agent failed: {exc}",
        )
