"""
Weighted scoring model for RCA candidates.

Uses default weights from RCA spec. Supports missing-signal weight redistribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rca_engine.signal_computation import SignalScores

# Default weights (sum = 1.0) per deterministic_rca_v1.md
DEFAULT_WEIGHTS: dict[str, float] = {
    "top_frame": 0.15,
    "frame_depth": 0.10,
    "last_touch_recency": 0.12,
    "deploy_proximity": 0.10,
    "deploy_recency_rank": 0.08,
    "historical_recurrence": 0.10,
    "trace_completeness": 0.10,
    "path_exclusion": 0.05,
    "deployment_timing_valid": 0.10,
    "file_frame_count": 0.10,
}

# Signals considered "unavailable" when 0 due to missing data (weight redistributed)
UNAVAILABLE_WHEN_ZERO = (
    "last_touch_recency",
    "deploy_proximity",
    "deploy_recency_rank",
    "deployment_timing_valid",
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


def _get_signal_values(s: SignalScores) -> dict[str, float]:
    return s.to_dict()


def _redistribute_weights(
    signal_values: dict[str, float],
    nominal_weights: dict[str, float],
) -> dict[str, float]:
    """
    Redistribute weight from unavailable signals to available ones.
    Unavailable = in UNAVAILABLE_WHEN_ZERO and value is 0.
    """
    unavailable = [
        k for k in UNAVAILABLE_WHEN_ZERO
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


def compute_score(
    signals: SignalScores,
    *,
    weights: Optional[dict[str, float]] = None,
    trace_completeness_cap_threshold: float = 0.8,
    max_confidence_when_partial: float = 0.7,
) -> RankedCandidate:
    """
    Compute weighted score with optional redistribution and confidence cap.

    Returns a placeholder RankedCandidate (file_id/frame_id set by caller).
    """
    weights = weights or DEFAULT_WEIGHTS
    vals = _get_signal_values(signals)
    w = _redistribute_weights(vals, weights)

    raw = sum(vals.get(k, 0) * w.get(k, 0) for k in w)
    trace_comp = vals.get("trace_completeness", 0)
    capped = raw
    if trace_comp < trace_completeness_cap_threshold:
        capped = min(raw, trace_comp * max_confidence_when_partial)

    return RankedCandidate(
        file_id="",
        frame_id="",
        frame_order=0,
        path="",
        score=raw,
        capped_score=capped,
        signal_scores=vals,
        weights_used=w,
    )


def rank_candidates(
    candidates: list,
    signal_scores: list[SignalScores],
    *,
    min_confidence: float = 0.25,
    top_n: int = 3,
    weights: Optional[dict[str, float]] = None,
    trace_completeness_cap_threshold: float = 0.8,
    max_confidence_when_partial: float = 0.7,
) -> list[RankedCandidate]:
    """
    Score and rank candidates. Returns top N with score >= min_confidence.

    Tie-breaker: frame_order asc, last_touch_recency desc, historical_recurrence desc, path asc.
    """
    if len(candidates) != len(signal_scores):
        return []

    ranked: list[RankedCandidate] = []
    for c, sig in zip(candidates, signal_scores):
        r = compute_score(
            sig,
            weights=weights,
            trace_completeness_cap_threshold=trace_completeness_cap_threshold,
            max_confidence_when_partial=max_confidence_when_partial,
        )
        score = r.capped_score if r.capped_score is not None else r.score
        if score < min_confidence:
            continue
        ranked.append(
            RankedCandidate(
                file_id=c.file_id,
                frame_id=c.representative_frame_id,
                frame_order=c.representative_frame_order,
                path=c.path,
                score=r.score,
                capped_score=r.capped_score,
                signal_scores=r.signal_scores,
                weights_used=r.weights_used,
            )
        )

    # Sort: score desc, frame_order asc, last_touch_recency desc, historical_recurrence desc, path asc
    def key(r: RankedCandidate) -> tuple:
        return (
            -r.capped_score if r.capped_score is not None else -r.score,
            r.frame_order,
            -r.signal_scores.get("last_touch_recency", 0),
            -r.signal_scores.get("historical_recurrence", 0),
            r.path or "",
        )

    ranked.sort(key=key)
    return ranked[:top_n]
