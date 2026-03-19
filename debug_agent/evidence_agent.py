"""Evidence agent: gather deterministic evidence for top RCA candidates."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from debug_agent.shared_types import DebugContext, EvidencePackage, StepKind, StepResult
from debug_agent.tool_registry import invoke

logger = logging.getLogger(__name__)


def _candidate_rows_from_rca_output(rca_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract candidate rows from RCAResult-like output payload."""
    candidates = rca_output.get("candidates") or []
    if not isinstance(candidates, list):
        return []
    out: list[dict[str, Any]] = []
    for c in candidates:
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
    return out


def _top_signal_summary(bundle: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    """Extract top signal summary from an evidence bundle."""
    scores = bundle.get("signal_scores") or {}
    if not isinstance(scores, dict):
        return []
    items = sorted(
        [(str(k), float(v) if isinstance(v, (int, float)) else 0.0) for k, v in scores.items()],
        key=lambda kv: (-kv[1], kv[0]),
    )[:limit]
    return [{"name": name, "score": score} for name, score in items]


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Gather deterministic evidence package for top RCA candidates.

    Inputs:
    - anomaly_id
    - optional RCA agent output payload (params["rca_result"])
    """
    payload = params or {}
    anomaly_id = str(payload.get("anomaly_id") or context.anomaly_id or "")
    rca_output = payload.get("rca_result") if isinstance(payload.get("rca_result"), dict) else {}

    if not anomaly_id:
        return StepResult(
            step_kind=StepKind.EVIDENCE,
            success=False,
            output={},
            error="missing anomaly_id",
        )

    logger.info("debug_agent.evidence_agent.start anomaly_id=%s", anomaly_id)

    try:
        # Prefer candidates coming from RCA agent output; fallback to active RCA results.
        candidate_rows = _candidate_rows_from_rca_output(rca_output)
        if not candidate_rows:
            raw_rows = invoke("get_rca_results", anomaly_id)
            candidate_rows = []
            for idx, row in enumerate(raw_rows[:3], start=1):
                candidate_rows.append(
                    {
                        "rank": idx,
                        "file_id": str(row.get("file_id") or ""),
                        "path": str(row.get("path") or ""),
                        "confidence": float(row.get("confidence") or 0.0),
                        "evidence_ref": str(row.get("evidence_ref") or ""),
                    }
                )
        else:
            candidate_rows = sorted(candidate_rows, key=lambda c: (c.get("rank") or 10_000))[:3]

        deployment_ctx = invoke("get_deployment_context", anomaly_id)

        bullets: list[str] = []
        signal_summaries: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        candidate_evidence: list[dict[str, Any]] = []

        for c in candidate_rows:
            file_id = c.get("file_id") or ""
            path = c.get("path") or ""
            evidence_ref = c.get("evidence_ref") or ""

            bundle = invoke("get_evidence_bundle", evidence_ref) if evidence_ref else None
            commits = invoke("get_related_commits", file_id) if file_id else []
            top_signals = _top_signal_summary(bundle or {}, limit=3)

            if evidence_ref:
                evidence_refs.append(evidence_ref)
            if top_signals:
                signal_summaries.append(
                    {
                        "file_id": file_id,
                        "path": path,
                        "signals": top_signals,
                    }
                )

            # Compact textual highlights for reporting/explanation reuse.
            if path:
                bullets.append(f"Candidate {c.get('rank')}: {path} (confidence {c.get('confidence', 0.0):.2f}).")
            if top_signals:
                formatted = ", ".join(f"{s['name']}={s['score']:.2f}" for s in top_signals)
                bullets.append(f"Top graph signals for {path or file_id}: {formatted}.")
            if commits:
                latest = commits[0]
                bullets.append(
                    f"Recent commit for {path or file_id}: {latest.get('sha', '')} at {latest.get('timestamp', '')}."
                )
            if isinstance(bundle, dict) and bundle.get("deployment_id"):
                bullets.append(
                    f"Bundle-linked deployment for {path or file_id}: {bundle.get('deployment_id')}."
                )

            candidate_evidence.append(
                {
                    "rank": c.get("rank"),
                    "file_id": file_id,
                    "path": path,
                    "confidence": c.get("confidence"),
                    "evidence_ref": evidence_ref,
                    "signal_summary": top_signals,
                    "commit_highlights": commits[:3],
                    "deployment_highlights": {
                        "bundle_deployment_id": (bundle or {}).get("deployment_id") if isinstance(bundle, dict) else "",
                        "anomaly_deployment_context": deployment_ctx.get("deployments", [])[:3]
                        if isinstance(deployment_ctx, dict) else [],
                    },
                    "evidence_highlights": {
                        "bundle_present": bool(bundle),
                        "bundle_keys": sorted(list(bundle.keys()))[:12] if isinstance(bundle, dict) else [],
                    },
                }
            )

        package = EvidencePackage(
            anomaly_id=anomaly_id,
            bullets=bullets[:24],
            signal_summaries=signal_summaries,
            evidence_refs=evidence_refs,
            metadata={
                "candidate_evidence": candidate_evidence,
                "candidate_count": len(candidate_rows),
                "deployment_context": deployment_ctx if isinstance(deployment_ctx, dict) else {},
                "evidence_status": "complete" if candidate_rows else "no_candidates",
            },
        )

        if not candidate_rows:
            logger.warning("debug_agent.evidence_agent.no_candidates anomaly_id=%s", anomaly_id)
            return StepResult(
                step_kind=StepKind.EVIDENCE,
                success=False,
                output=asdict(package),
                error="no RCA candidates available for evidence collection",
            )

        logger.info(
            "debug_agent.evidence_agent.done anomaly_id=%s candidates=%s refs=%s",
            anomaly_id,
            len(candidate_rows),
            len(evidence_refs),
        )
        return StepResult(
            step_kind=StepKind.EVIDENCE,
            success=True,
            output=asdict(package),
            error=None,
        )
    except Exception as exc:
        logger.exception("debug_agent.evidence_agent.error anomaly_id=%s error=%s", anomaly_id, str(exc))
        fallback = EvidencePackage(
            anomaly_id=anomaly_id,
            bullets=[],
            signal_summaries=[],
            evidence_refs=[],
            metadata={"evidence_status": "failed"},
        )
        return StepResult(
            step_kind=StepKind.EVIDENCE,
            success=False,
            output=asdict(fallback),
            error=f"evidence_agent failed: {exc}",
        )
