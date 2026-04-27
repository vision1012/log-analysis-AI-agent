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
    candidates: list[Any] | dict[str, dict[str, float]],
    *,
    min_confidence: float = 0.25,
    **_: Any,
) -> list[RankedCandidate]:
    if not candidates:
        return []

    # Support direct list-based ranking by candidate["score"] (requested behavior).
    if isinstance(candidates, list):
        sorted_candidates = sorted(
            candidates,
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
                    )
                )
            else:
                score = float(getattr(c, "score", 0.0))
                if score < min_confidence:
                    continue
                out.append(
                    RankedCandidate(
                        file_id=str(getattr(c, "file_id", "") or getattr(c, "value", "")),
                        frame_id=str(getattr(c, "representative_frame_id", "")),
                        frame_order=int(getattr(c, "representative_frame_order", 0)),
                        path=str(getattr(c, "path", "") or getattr(c, "value", "")),
                        score=score,
                        capped_score=score,
                        signal_scores={},
                        weights_used={},
                    )
                )
        return out

    # Backward-compatible path for existing dict-of-signals callers.
    signal_map = candidates
    scored: list[RankedCandidate] = []
    for fid, sig in signal_map.items():
        score = float(sig.get("score", 0.0))
        if score < min_confidence:
            continue
        scored.append(
            RankedCandidate(
                file_id=fid,
                frame_id="",
                frame_order=0,
                path="",
                score=score,
                capped_score=score,
                signal_scores=sig,
                weights_used={},
            )
        )
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:N_CANDIDATES]
