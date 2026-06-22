"""Tests for deterministic RCA ranking with MCP score breakdown."""

from __future__ import annotations

import pytest

from rca_engine.candidate_generator import Candidate, RepresentativeFrame
from rca_engine.ranking_model import rank_candidates


def _candidate(file_id: str, path: str, order: int = 0) -> Candidate:
    return Candidate(
        file_id=file_id,
        representative_frame=RepresentativeFrame(frame_id=f"frame-{file_id}", frame_order=order),
        path=path,
    )


def test_rank_candidates_preserves_existing_signals_and_adds_breakdown(monkeypatch) -> None:
    monkeypatch.setenv("MCP_RCA_SIGNALS_ENABLED", "true")
    signals = {
        "file-a": {
            "top_frame_presence": 1.0,
            "frame_depth_penalty": 0.0,
            "last_touch_recency": 0.8,
            "deploy_proximity": 0.5,
            "deploy_recency_rank": 1.0,
            "historical_recurrence": 0.2,
            "resolution_quality": 0.9,
            "spike_correlation_strength": 0.5,
            "trace_completeness": 0.9,
            "file_touch_sparsity": 0.4,
            "deployment_proximity_mcp": 1.0,
            "alert_correlation": 1.0,
            "incident_severity": 0.0,
            "known_issue_match": 0.0,
            "historical_investigation": 0.0,
            "score_breakdown": {"deployment_proximity": 12.0, "alert_correlation": 10.0},
        },
        "file-b": {
            "top_frame_presence": 0.0,
            "frame_depth_penalty": 0.5,
            "last_touch_recency": 0.3,
            "deploy_proximity": 0.0,
            "deploy_recency_rank": 0.0,
            "historical_recurrence": 0.0,
            "resolution_quality": 0.5,
            "spike_correlation_strength": 0.0,
            "trace_completeness": 0.9,
            "file_touch_sparsity": 0.2,
            "deployment_proximity_mcp": 0.0,
            "alert_correlation": 0.0,
            "incident_severity": 0.0,
            "known_issue_match": 0.0,
            "historical_investigation": 0.0,
            "score_breakdown": {},
        },
    }

    ranked = rank_candidates(
        signals,
        candidates=[_candidate("file-a", "/srv/auth/handler.py", 0), _candidate("file-b", "/srv/other.py", 2)],
        min_confidence=0.25,
    )

    assert len(ranked) == 2
    assert ranked[0].file_id == "file-a"
    assert ranked[0].score > ranked[1].score
    assert ranked[0].score_breakdown.get("deployment_proximity") == 12.0
    assert ranked[0].score_breakdown.get("alert_correlation") == 10.0
    assert "top_frame_presence" in ranked[0].score_breakdown
    assert ranked[0].weights_used


def test_rank_candidates_mcp_boost_can_change_order(monkeypatch) -> None:
    monkeypatch.setenv("MCP_RCA_SIGNALS_ENABLED", "true")
    base = {
        "top_frame_presence": 1.0,
        "frame_depth_penalty": 0.0,
        "last_touch_recency": 0.5,
        "deploy_proximity": 0.5,
        "deploy_recency_rank": 0.0,
        "historical_recurrence": 0.0,
        "resolution_quality": 0.8,
        "spike_correlation_strength": 0.5,
        "trace_completeness": 0.9,
        "file_touch_sparsity": 0.3,
        "deployment_proximity_mcp": 0.0,
        "alert_correlation": 0.0,
        "incident_severity": 0.0,
        "known_issue_match": 0.0,
        "historical_investigation": 0.0,
    }
    signals = {
        "file-a": {**base, "score_breakdown": {}},
        "file-b": {
            **base,
            "known_issue_match": 1.0,
            "score_breakdown": {"known_issue_match": 8.0},
        },
    }
    ranked = rank_candidates(
        signals,
        candidates=[_candidate("file-a", "/srv/a.py"), _candidate("file-b", "/srv/auth/handler.py")],
        min_confidence=0.25,
    )
    assert ranked[0].file_id == "file-b"
    assert ranked[0].score_breakdown.get("known_issue_match") == 8.0
