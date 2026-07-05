"""
Weighted scoring model for RCA candidates.

Weighted sum scoring with default weights from RCA spec.
Handles missing signals via weight redistribution.
Caps confidence when trace_completeness < 0.5.
Includes MCP-derived point contributions in score_breakdown.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from rca_engine.candidate_generator import Candidate
from rca_engine.mcp_signal_config import mcp_point_scale, mcp_rca_signals_enabled
from rca_engine.signal_computation import MCP_SIGNAL_NAMES, SIGNAL_NAMES
from rca_engine.mcp_context_signals import MCP_CONTEXT_SIGNAL_NAMES
from rca_engine.mcp_signal_v2_config import MCP_SIGNAL_V2_NAMES

N_CANDIDATES = 3
TRACE_COMPLETENESS_CAP_THRESHOLD = 0.5
MAX_CONFIDENCE_WHEN_PARTIAL = 0.7

DEFAULT_WEIGHTS: dict[str, float] = {
    "top_frame_presence": 0.15,
    "frame_depth_penalty": 0.10,
    "last_touch_recency": 0.12,
    "deploy_proximity": 0.10,
    "deploy_recency_rank": 0.08,
    "historical_recurrence": 0.10,
    "resolution_quality": 0.10,
    "spike_correlation_strength": 0.08,
    "trace_completeness": 0.10,
    "file_touch_sparsity": 0.07,
    "keyword_alignment": 0.08,
}

MCP_DEFAULT_WEIGHTS: dict[str, float] = {
    "deployment_proximity_mcp": 0.04,
    "alert_correlation": 0.03,
    "incident_severity": 0.03,
    "known_issue_match": 0.03,
    "historical_investigation": 0.02,
}

MCP_CONTEXT_WEIGHTS: dict[str, float] = {
    "recent_commit_match": 0.03,
    "recent_pr_match": 0.025,
    "changed_file_match": 0.035,
    "jira_ticket_match": 0.02,
    "jira_label_match": 0.015,
    "author_activity_match": 0.025,
}

MCP_SIGNAL_V2_WEIGHTS: dict[str, float] = {
    "code_ownership": 0.025,
    "code_churn": 0.03,
    "deployment_proximity_v2": 0.03,
    "rollback": 0.025,
    "build_failure": 0.025,
    "service_dependency": 0.02,
    "incident_recurrence": 0.025,
    "alert_correlation_v2": 0.03,
    "reviewer": 0.02,
    "author_expertise": 0.025,
}

UNAVAILABLE_WHEN_ZERO = (
    "last_touch_recency",
    "deploy_proximity",
    "deploy_recency_rank",
    "spike_correlation_strength",
    "keyword_alignment",
    "deployment_proximity_mcp",
    "alert_correlation",
    "incident_severity",
    "known_issue_match",
    "historical_investigation",
    *MCP_CONTEXT_SIGNAL_NAMES,
    *MCP_SIGNAL_V2_NAMES,
)


@dataclass
class RankedCandidate:
    """Candidate with computed score and optional cap."""

    file_id: str
    frame_id: str
    frame_order: int
    path: str
    score: float
    capped_score: Optional[float]
    signal_scores: dict[str, float]
    weights_used: dict[str, float]
    score_breakdown: dict[str, float] = field(default_factory=dict)


def _env_weights(prefix: str, defaults: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, default in defaults.items():
        env_name = f"{prefix}_{key.upper()}"
        raw = (os.environ.get(env_name) or "").strip()
        if not raw:
            out[key] = default
            continue
        try:
            out[key] = float(raw)
        except ValueError:
            out[key] = default
    return out


def effective_weights() -> dict[str, float]:
    base = _env_weights("RCA_WEIGHT", DEFAULT_WEIGHTS)
    if mcp_rca_signals_enabled():
        base.update(_env_weights("MCP_RCA_WEIGHT", MCP_DEFAULT_WEIGHTS))
        base.update(_env_weights("MCP_CTX_WEIGHT", MCP_CONTEXT_WEIGHTS))
        from rca_engine.mcp_signal_v2_config import mcp_signal_v2_enabled

        if mcp_signal_v2_enabled():
            base.update(_env_weights("MCP_V2_WEIGHT", MCP_SIGNAL_V2_WEIGHTS))
    total = sum(base.values()) or 1.0
    if abs(total - 1.0) > 0.001:
        base = {k: v / total for k, v in base.items()}
    return base


def _redistribute_weights(
    signal_values: dict[str, float],
    nominal_weights: dict[str, float],
) -> dict[str, float]:
    unavailable = [
        k
        for k in UNAVAILABLE_WHEN_ZERO
        if k in nominal_weights and signal_values.get(k, 0) == 0
    ]
    if not unavailable:
        return dict(nominal_weights)

    available = [k for k in nominal_weights if k not in unavailable]
    sum_unavail = sum(nominal_weights.get(k, 0) for k in unavailable)
    sum_avail = sum(nominal_weights.get(k, 0) for k in available)
    if sum_avail <= 0:
        return dict(nominal_weights)

    out: dict[str, float] = {}
    for k in nominal_weights:
        if k in unavailable:
            out[k] = 0.0
        else:
            w = nominal_weights[k]
            out[k] = w + (w / sum_avail) * sum_unavail
    return out


def _effective_value(signal_name: str, value: float) -> float:
    if signal_name == "frame_depth_penalty":
        return 1.0 - value
    return value


def _extract_score_breakdown(raw: dict[str, Any]) -> dict[str, float]:
    breakdown = raw.pop("score_breakdown", None)
    if not isinstance(breakdown, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in breakdown.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _base_breakdown_points(
    signal_values: dict[str, float],
    weights: dict[str, float],
) -> dict[str, float]:
    points: dict[str, float] = {}
    scale = mcp_point_scale()
    for name in SIGNAL_NAMES:
        if name not in weights:
            continue
        contrib = _effective_value(name, signal_values.get(name, 0.0)) * weights[name] * scale
        if contrib > 0:
            points[name] = round(contrib, 2)
    return points


def _score_one(
    file_id: str,
    raw_signals: dict[str, Any],
    *,
    weights: dict[str, float],
) -> tuple[float, float, dict[str, float], dict[str, float], dict[str, float]]:
    mcp_breakdown = _extract_score_breakdown(raw_signals)
    signal_values = {
        k: float(raw_signals.get(k, 0.0))
        for k in (*SIGNAL_NAMES, *MCP_SIGNAL_NAMES, *MCP_CONTEXT_SIGNAL_NAMES, *MCP_SIGNAL_V2_NAMES)
        if k in raw_signals and not isinstance(raw_signals.get(k), dict)
    }
    used_weights = _redistribute_weights(signal_values, weights)

    base_score = 0.0
    for name, weight in used_weights.items():
        if name not in signal_values:
            continue
        base_score += _effective_value(name, signal_values.get(name, 0.0)) * weight

    breakdown = _base_breakdown_points(signal_values, used_weights)
    breakdown.update(mcp_breakdown)

    mcp_bonus = sum(mcp_breakdown.values()) / mcp_point_scale()
    score = min(1.0, base_score + mcp_bonus)

    trace_completeness = signal_values.get("trace_completeness", 1.0)
    capped = score
    if trace_completeness < TRACE_COMPLETENESS_CAP_THRESHOLD:
        capped = min(score, MAX_CONFIDENCE_WHEN_PARTIAL)

    return score, capped, signal_values, used_weights, breakdown


def rank_candidates(
    signal_scores_by_file: dict[str, dict[str, Any]] | list[Any],
    *,
    candidates: list[Candidate] | None = None,
    min_confidence: float = 0.25,
    **_: Any,
) -> list[RankedCandidate]:
    if not signal_scores_by_file:
        return []

    if isinstance(signal_scores_by_file, list):
        sorted_candidates = sorted(
            signal_scores_by_file,
            key=lambda x: (x.get("score", 0.0) if isinstance(x, dict) else float(getattr(x, "score", 0.0))),
            reverse=True,
        )
        out: list[RankedCandidate] = []
        for c in sorted_candidates[:N_CANDIDATES]:
            if isinstance(c, dict):
                score = float(c.get("score", 0.0))
                if score < min_confidence:
                    continue
                out.append(
                    RankedCandidate(
                        file_id=str(c.get("file_id") or c.get("value") or ""),
                        frame_id=str(c.get("frame_id") or ""),
                        frame_order=int(c.get("frame_order") or 0),
                        path=str(c.get("path") or c.get("value") or ""),
                        score=score,
                        capped_score=score,
                        signal_scores={},
                        weights_used={},
                        score_breakdown=dict(c.get("score_breakdown") or {}),
                    )
                )
        return out

    weights = effective_weights()
    cand_by_file: dict[str, Candidate] = {}
    if candidates:
        cand_by_file = {c.file_id: c for c in candidates}

    scored: list[RankedCandidate] = []
    for fid, raw in signal_scores_by_file.items():
        if not isinstance(raw, dict):
            continue
        score, capped, signal_values, used_weights, breakdown = _score_one(fid, dict(raw), weights=weights)
        if capped < min_confidence:
            continue
        cand = cand_by_file.get(fid)
        scored.append(
            RankedCandidate(
                file_id=fid,
                frame_id=cand.representative_frame_id if cand else "",
                frame_order=cand.representative_frame_order if cand else 0,
                path=cand.path if cand else "",
                score=score,
                capped_score=capped,
                signal_scores=signal_values,
                weights_used=used_weights,
                score_breakdown=breakdown,
            )
        )

    scored.sort(
        key=lambda r: (
            -(r.capped_score if r.capped_score is not None else r.score),
            r.frame_order,
            -r.signal_scores.get("last_touch_recency", 0.0),
            -r.signal_scores.get("historical_recurrence", 0.0),
            r.path,
        )
    )
    return scored[:N_CANDIDATES]
