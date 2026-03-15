"""
Weighted scoring model for RCA candidates.

Weighted sum scoring with default weights from RCA spec.
Handles missing signals via weight redistribution.
Caps confidence when trace_completeness < 0.5.
Returns top N_candidates = 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Default weights from RCA spec (deterministic_rca_v1.md). Sum = 1.0.
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
}

# Signals considered "unavailable" when 0 due to missing data (weight redistributed)
UNAVAILABLE_WHEN_ZERO = (
    "last_touch_recency",
    "deploy_proximity",
    "deploy_recency_rank",
    "spike_correlation_strength",
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


def _redistribute_weights(
    signal_values: dict[str, float],
    nominal_weights: dict[str, float],
) -> dict[str, float]:
    """Redistribute weight from unavailable signals to available ones."""
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


def _effective_value(signal_name: str, value: float) -> float:
    """frame_depth_penalty is inverted: higher penalty = lower score."""
    if signal_name == "frame_depth_penalty":
        return 1.0 - value
    return value


def rank_candidates(
    candidate_signals: dict[str, dict[str, float]],
    *,
    candidates: Optional[list[Any]] = None,
    min_confidence: float = 0.25,
    weights: Optional[dict[str, float]] = None,
) -> list[RankedCandidate]:
    """
    Rank candidates by weighted sum scoring.

    Args:
        candidate_signals: {file_id: {signal_name: score}} from compute_signals.
        candidates: Optional list of Candidate for metadata (frame_id, path, frame_order).
                    If omitted, uses empty defaults for tie-breaking.

    Returns:
        Top N_candidates=3, sorted by capped score desc, then tie-breakers.
        Cap applied when trace_completeness < 0.5.
    """
    weights = weights or DEFAULT_WEIGHTS
    cand_by_file = {c.file_id: c for c in (candidates or [])}

    scored: list[tuple] = []
    for fid, sig in candidate_signals.items():
        w = _redistribute_weights(sig, weights)
        raw = sum(
            _effective_value(k, sig.get(k, 0)) * w.get(k, 0)
            for k in w
        )
        trace_comp = sig.get("trace_completeness", 0)
        capped = raw
        if trace_comp < TRACE_COMPLETENESS_CAP_THRESHOLD:
            capped = min(raw, trace_comp * MAX_CONFIDENCE_WHEN_PARTIAL)

        if capped < min_confidence:
            continue

        c = cand_by_file.get(fid)
        frame_id = c.representative_frame_id if c else ""
        frame_order = c.representative_frame_order if c else 999
        path = c.path if c else ""

        scored.append((fid, raw, capped, sig, w, frame_id, frame_order, path))

    # Sort: score desc, frame_order asc, last_touch_recency desc, historical_recurrence desc, path asc
    def key(item: tuple) -> tuple:
        _, _, capped, sig, _, _, frame_order, path = item
        return (
            -capped,
            frame_order,
            -sig.get("last_touch_recency", 0),
            -sig.get("historical_recurrence", 0),
            path or "",
        )

    scored.sort(key=key)
    top = scored[:N_CANDIDATES]

    return [
        RankedCandidate(
            file_id=fid,
            frame_id=frame_id,
            frame_order=frame_order,
            path=path,
            score=raw,
            capped_score=capped,
            signal_scores=sig,
            weights_used=w,
        )
        for fid, raw, capped, sig, w, frame_id, frame_order, path in top
    ]
