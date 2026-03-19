"""Triage agent: deterministic anomaly prioritization and classification."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from graph.neo4j_client import Neo4jClient

from debug_agent.shared_types import DebugContext, StepKind, StepResult, TriageResult

logger = logging.getLogger(__name__)


def _safe_float(v: Any, default: float = 0.0) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _normalize_severity(value: str) -> str:
    v = (value or "").strip().lower()
    if v in {"critical", "high", "sev1", "p0", "p1"}:
        return "high"
    if v in {"medium", "med", "moderate", "sev2", "p2"}:
        return "medium"
    if v in {"low", "minor", "sev3", "p3"}:
        return "low"
    return ""


def _infer_error_type(text: str) -> str:
    t = (text or "").lower()
    if "timeout" in t or "timed out" in t:
        return "timeout"
    if "nullpointer" in t or "null pointer" in t or "none type" in t:
        return "null_pointer"
    if "connection refused" in t or "dns" in t or "network" in t or "infra" in t:
        return "infra"
    if "oom" in t or "out of memory" in t or "memory" in t:
        return "memory"
    if "permission" in t or "unauthorized" in t or "forbidden" in t or "auth" in t:
        return "auth"
    if "dependency" in t or "upstream" in t:
        return "dependency"
    return "unknown"


def _score_to_severity(score: float) -> str:
    if score >= 0.80:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run deterministic triage before RCA.

    Uses anomaly metadata and graph context only (no LLM).
    """
    payload = params or {}
    anomaly_id = str(payload.get("anomaly_id") or context.anomaly_id or "")
    if not anomaly_id:
        return StepResult(
            step_kind=StepKind.TRIAGE,
            success=False,
            output={},
            error="missing anomaly_id",
        )

    logger.info("debug_agent.triage_agent.start anomaly_id=%s", anomaly_id)

    client = Neo4jClient.from_env()
    try:
        client.connect()
        q = """
        MATCH (a:Anomaly {id: $anomaly_id})
        RETURN a.id AS anomaly_id,
               a.service_ref AS service_ref,
               a.severity AS severity,
               a.score AS score,
               a.error_type AS error_type,
               a.message AS message,
               a.title AS title,
               a.reason AS reason,
               a.trace_ref AS trace_ref
        """
        rows = client.execute_read(q, {"anomaly_id": anomaly_id})
        if not rows:
            fallback = TriageResult(
                anomaly_id=anomaly_id,
                severity="low",
                service_ref=None,
                error_type="unknown",
                confidence_score=0.20,
                priority="low",
                summary="Anomaly metadata not found; triage defaults to low severity.",
                classification="unknown",
                metadata={"triage_status": "missing_anomaly_metadata"},
            )
            logger.warning("debug_agent.triage_agent.no_anomaly anomaly_id=%s", anomaly_id)
            return StepResult(
                step_kind=StepKind.TRIAGE,
                success=False,
                output=asdict(fallback),
                error="anomaly not found",
            )

        row = rows[0]
        service_ref = row.get("service_ref")
        score = _safe_float(row.get("score"), 0.0)

        explicit_severity = _normalize_severity(str(row.get("severity") or ""))
        severity = explicit_severity or _score_to_severity(score)

        explicit_error_type = str(row.get("error_type") or "").strip().lower()
        raw_text = " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("message") or ""),
                str(row.get("reason") or ""),
            ]
        ).strip()
        error_type = explicit_error_type or _infer_error_type(raw_text)

        confidence_signals = 0
        if explicit_severity:
            confidence_signals += 1
        if service_ref:
            confidence_signals += 1
        if explicit_error_type or raw_text:
            confidence_signals += 1
        if score > 0:
            confidence_signals += 1
        confidence_score = round(confidence_signals / 4.0, 2)

        summary = (
            f"Triage {severity}: service={service_ref or 'unknown'}, "
            f"error_type={error_type}, signal_confidence={confidence_score:.2f}."
        )
        triage = TriageResult(
            anomaly_id=anomaly_id,
            severity=severity,
            service_ref=str(service_ref) if service_ref else None,
            error_type=error_type,
            confidence_score=confidence_score,
            # compatibility aliases used by earlier contracts
            priority=severity,
            summary=summary,
            classification=error_type,
            metadata={
                "triage_status": "completed",
                "score": score,
                "trace_ref": row.get("trace_ref") or "",
                "signals_present": confidence_signals,
            },
        )
        logger.info(
            "debug_agent.triage_agent.done anomaly_id=%s severity=%s error_type=%s conf=%s",
            anomaly_id,
            severity,
            error_type,
            confidence_score,
        )
        return StepResult(
            step_kind=StepKind.TRIAGE,
            success=True,
            output=asdict(triage),
            error=None,
        )
    except Exception as exc:
        logger.exception("debug_agent.triage_agent.error anomaly_id=%s error=%s", anomaly_id, str(exc))
        fallback = TriageResult(
            anomaly_id=anomaly_id,
            severity="low",
            service_ref=None,
            error_type="unknown",
            confidence_score=0.10,
            priority="low",
            summary="Triage failed; returning safe low-severity fallback.",
            classification="unknown",
            metadata={"triage_status": "failed"},
        )
        return StepResult(
            step_kind=StepKind.TRIAGE,
            success=False,
            output=asdict(fallback),
            error=f"triage_agent failed: {exc}",
        )
    finally:
        try:
            client.close()
        except Exception:
            pass
