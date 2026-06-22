"""
RCA Confidence Engine — separate from ranking.

Computes evidence-based confidence with supporting and contradicting factors.
Does not influence candidate ranking order.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from rca_engine.ranking_model import RankedCandidate

CONFIDENCE_LEVEL_HIGH = 0.75
CONFIDENCE_LEVEL_MEDIUM = 0.50


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw)
    except ValueError:
        return default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _signal(signals: dict[str, float], name: str) -> float:
    try:
        return float(signals.get(name, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _confidence_level(score: float) -> str:
    if score >= CONFIDENCE_LEVEL_HIGH:
        return "high"
    if score >= CONFIDENCE_LEVEL_MEDIUM:
        return "medium"
    return "low"


@dataclass
class ConfidenceAssessment:
    """Evidence-based confidence for one RCA candidate."""

    candidate: str
    confidence: float
    confidence_level: str
    supporting_factors: list[str] = field(default_factory=list)
    contradicting_factors: list[str] = field(default_factory=list)
    evidence_breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "confidence": round(self.confidence, 4),
            "confidence_level": self.confidence_level,
            "supporting_factors": list(self.supporting_factors),
            "contradicting_factors": list(self.contradicting_factors),
            "evidence_breakdown": dict(self.evidence_breakdown),
        }


def _has_conflicting_alerts(graph_context: dict[str, Any] | None) -> bool:
    if not isinstance(graph_context, dict):
        return False
    alerts = graph_context.get("related_alerts") or []
    if not isinstance(alerts, list) or len(alerts) < 2:
        return False
    severities: set[str] = set()
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        sev = str(alert.get("severity") or "").strip().lower()
        if sev:
            severities.add(sev)
    critical = {"critical", "high", "sev1"}
    warning = {"warning", "medium", "warn", "sev2"}
    return bool(severities & critical) and bool(severities & warning)


def _has_deployment_activity(graph_context: dict[str, Any] | None) -> bool:
    if not isinstance(graph_context, dict):
        return False
    deployments = graph_context.get("related_deployments") or []
    return isinstance(deployments, list) and len(deployments) > 0


def compute_confidence_assessment(
    *,
    candidate_path: str,
    candidate_file_id: str = "",
    signal_scores: dict[str, float],
    score_breakdown: dict[str, float] | None = None,
    graph_context: dict[str, Any] | None = None,
) -> ConfidenceAssessment:
    """
    Compute evidence-based confidence for one ranked candidate.

    Ranking score is intentionally not used — confidence is derived from
    signal strength and MCP/graph correlation factors only.
    """
    candidate = (candidate_path or candidate_file_id or "").strip()
    signals = signal_scores or {}
    breakdown: dict[str, float] = {}

    base = _env_float("RCA_CONFIDENCE_BASE", 0.50)
    score = base
    supporting: list[str] = []
    contradicting: list[str] = []

    deploy_mcp = _signal(signals, "deployment_proximity_mcp")
    if deploy_mcp >= 1.0:
        delta = _env_float("RCA_CONFIDENCE_DEPLOY_0_5", 0.12)
        score += delta
        breakdown["deployment_proximity"] = delta
        supporting.append("Deployment occurred within 5 minutes of incident")
    elif deploy_mcp >= 0.67:
        delta = _env_float("RCA_CONFIDENCE_DEPLOY_5_15", 0.08)
        score += delta
        breakdown["deployment_proximity"] = delta
        supporting.append("Deployment occurred within 15 minutes of incident")
    elif deploy_mcp >= 0.33:
        delta = _env_float("RCA_CONFIDENCE_DEPLOY_15_30", 0.04)
        score += delta
        breakdown["deployment_proximity"] = delta
        supporting.append("Deployment occurred within 30 minutes of incident")

    if _signal(signals, "known_issue_match") >= 1.0:
        delta = _env_float("RCA_CONFIDENCE_KNOWN_ISSUE", 0.10)
        score += delta
        breakdown["known_issue_match"] = delta
        supporting.append("Matches documented known issue")

    hist_inv = _signal(signals, "historical_investigation")
    hist_rec = _signal(signals, "historical_recurrence")
    if hist_inv >= 0.7:
        delta = _env_float("RCA_CONFIDENCE_HISTORICAL_INVESTIGATION", 0.08)
        score += delta
        breakdown["historical_investigation"] = delta
        supporting.append("Prior investigations attributed same file or service")
    if hist_rec >= 0.4:
        delta = _env_float("RCA_CONFIDENCE_HISTORICAL_RECURRENCE", 0.06)
        score += delta
        breakdown["historical_recurrence"] = delta
        supporting.append("Repeated historical incidents for this file")

    alert_corr = _signal(signals, "alert_correlation")
    if alert_corr >= 1.0:
        delta = _env_float("RCA_CONFIDENCE_CRITICAL_ALERT", 0.08)
        score += delta
        breakdown["alert_correlation"] = delta
        supporting.append("Critical alert alignment")
    elif alert_corr >= 0.6:
        delta = _env_float("RCA_CONFIDENCE_WARNING_ALERT", 0.04)
        score += delta
        breakdown["alert_correlation"] = delta
        supporting.append("Warning alert correlation")

    top_frame = _signal(signals, "top_frame_presence")
    trace_complete = _signal(signals, "trace_completeness")
    resolution = _signal(signals, "resolution_quality")
    last_touch = _signal(signals, "last_touch_recency")
    deploy_prox = _signal(signals, "deploy_proximity")

    graph_strength = top_frame + trace_complete + resolution + last_touch + deploy_prox
    if graph_strength >= 3.0:
        delta = _env_float("RCA_CONFIDENCE_STRONG_GRAPH", 0.10)
        score += delta
        breakdown["strong_graph_evidence"] = delta
        supporting.append("Strong graph evidence (stack trace, recency, resolution)")
    elif graph_strength >= 2.0:
        delta = _env_float("RCA_CONFIDENCE_MODERATE_GRAPH", 0.05)
        score += delta
        breakdown["moderate_graph_evidence"] = delta
        supporting.append("Moderate graph evidence supports attribution")

    if top_frame >= 1.0:
        supporting.append("Candidate appears in top stack frame")

    if trace_complete < 0.5:
        delta = _env_float("RCA_CONFIDENCE_WEAK_TRACE_PENALTY", 0.10)
        score -= delta
        breakdown["weak_trace"] = -delta
        contradicting.append("Incomplete stack trace weakens evidence")

    deploy_graph = deploy_prox + _signal(signals, "deploy_recency_rank")
    if deploy_mcp <= 0 and deploy_graph <= 0 and not _has_deployment_activity(graph_context):
        delta = _env_float("RCA_CONFIDENCE_NO_DEPLOYMENT_PENALTY", 0.05)
        score -= delta
        breakdown["no_deployment_activity"] = -delta
        contradicting.append("No deployment activity near incident")

    if hist_inv <= 0 and hist_rec <= 0:
        delta = _env_float("RCA_CONFIDENCE_NO_HISTORICAL_PENALTY", 0.04)
        score -= delta
        breakdown["no_historical_match"] = -delta
        contradicting.append("No historical match for this file or service")

    if _has_conflicting_alerts(graph_context):
        delta = _env_float("RCA_CONFIDENCE_CONFLICTING_ALERTS_PENALTY", 0.05)
        score -= delta
        breakdown["conflicting_alerts"] = -delta
        contradicting.append("Conflicting alert severities in investigation context")

    if graph_strength < 1.5:
        delta = _env_float("RCA_CONFIDENCE_WEAK_EVIDENCE_PENALTY", 0.08)
        score -= delta
        breakdown["weak_evidence"] = -delta
        contradicting.append("Weak overall graph evidence")

    if isinstance(score_breakdown, dict):
        for key, value in score_breakdown.items():
            try:
                points = float(value)
            except (TypeError, ValueError):
                continue
            if points > 0 and key not in breakdown:
                breakdown[f"score_{key}"] = round(points / 100.0, 4)

    final = round(_clamp(score), 4)
    return ConfidenceAssessment(
        candidate=candidate,
        confidence=final,
        confidence_level=_confidence_level(final),
        supporting_factors=supporting,
        contradicting_factors=contradicting,
        evidence_breakdown=breakdown,
    )


def compute_confidence_for_ranked(
    ranked: list[RankedCandidate],
    *,
    graph_context: dict[str, Any] | None = None,
) -> list[ConfidenceAssessment]:
    """Compute confidence assessments for ranked candidates (ranking order preserved)."""
    out: list[ConfidenceAssessment] = []
    for r in ranked:
        out.append(
            compute_confidence_assessment(
                candidate_path=r.path,
                candidate_file_id=r.file_id,
                signal_scores=r.signal_scores,
                score_breakdown=r.score_breakdown,
                graph_context=graph_context,
            )
        )
    return out


def build_confidence_reasoning(assessment: ConfidenceAssessment | dict[str, Any]) -> str:
    """Human-readable confidence explanation for GraphRAG reports."""
    if isinstance(assessment, ConfidenceAssessment):
        data = assessment.to_dict()
    else:
        data = assessment

    candidate = str(data.get("candidate") or "candidate")
    confidence = float(data.get("confidence") or 0.0)
    level = str(data.get("confidence_level") or "low")
    supporting = data.get("supporting_factors") or []
    contradicting = data.get("contradicting_factors") or []

    parts = [
        f"Confidence for {candidate} is {confidence:.2f} ({level}).",
    ]
    if supporting:
        parts.append("Supporting factors: " + "; ".join(str(s) for s in supporting[:6]) + ".")
    if contradicting:
        parts.append("Contradicting factors: " + "; ".join(str(c) for c in contradicting[:6]) + ".")
    if not supporting and not contradicting:
        parts.append("Limited corroborating evidence available.")
    return " ".join(parts)
