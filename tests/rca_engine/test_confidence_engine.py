"""Tests for RCA confidence engine (separate from ranking)."""

from __future__ import annotations

from rca_engine.candidate_generator import Candidate, RepresentativeFrame
from rca_engine.confidence_engine import (
    build_confidence_reasoning,
    compute_confidence_assessment,
    compute_confidence_for_ranked,
)
from rca_engine.ranking_model import RankedCandidate, rank_candidates


def _ranked(file_id: str, path: str, signals: dict, breakdown: dict | None = None) -> RankedCandidate:
    return RankedCandidate(
        file_id=file_id,
        frame_id=f"frame-{file_id}",
        frame_order=0,
        path=path,
        score=0.6,
        capped_score=0.6,
        signal_scores=signals,
        weights_used={},
        score_breakdown=breakdown or {},
    )


def test_high_confidence_with_strong_positive_factors() -> None:
    assessment = compute_confidence_assessment(
        candidate_path="/srv/auth/handler.py",
        signal_scores={
            "deployment_proximity_mcp": 1.0,
            "known_issue_match": 1.0,
            "alert_correlation": 1.0,
            "historical_investigation": 0.8,
            "historical_recurrence": 0.6,
            "top_frame_presence": 1.0,
            "trace_completeness": 0.9,
            "resolution_quality": 0.9,
            "last_touch_recency": 0.8,
            "deploy_proximity": 0.7,
        },
        graph_context={
            "related_deployments": [{"deployment_id": "d1"}],
            "related_alerts": [{"severity": "critical"}],
        },
    )
    assert assessment.confidence >= 0.75
    assert assessment.confidence_level == "high"
    assert any("Deployment" in f for f in assessment.supporting_factors)
    assert any("known issue" in f.lower() for f in assessment.supporting_factors)
    assert any("Critical alert" in f for f in assessment.supporting_factors)


def test_contradicting_factors_lower_confidence() -> None:
    assessment = compute_confidence_assessment(
        candidate_path="/srv/other.py",
        signal_scores={
            "deployment_proximity_mcp": 0.0,
            "known_issue_match": 0.0,
            "alert_correlation": 0.0,
            "historical_investigation": 0.0,
            "historical_recurrence": 0.0,
            "top_frame_presence": 0.0,
            "trace_completeness": 0.3,
            "resolution_quality": 0.2,
            "last_touch_recency": 0.1,
            "deploy_proximity": 0.0,
        },
        graph_context={
            "related_alerts": [
                {"severity": "critical"},
                {"severity": "warning"},
            ],
        },
    )
    assert assessment.confidence < 0.6
    assert assessment.contradicting_factors
    assert any("trace" in f.lower() for f in assessment.contradicting_factors)
    assert any("Conflicting" in f for f in assessment.contradicting_factors)


def test_confidence_does_not_change_ranking_order() -> None:
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
            "deployment_proximity_mcp": 0.0,
            "alert_correlation": 0.0,
            "incident_severity": 0.0,
            "known_issue_match": 0.0,
            "historical_investigation": 0.0,
            "score_breakdown": {},
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
            "deployment_proximity_mcp": 1.0,
            "alert_correlation": 1.0,
            "incident_severity": 1.0,
            "known_issue_match": 1.0,
            "historical_investigation": 0.9,
            "score_breakdown": {"deployment_proximity": 12.0},
        },
    }
    candidates = [
        Candidate(
            file_id="file-a",
            representative_frame=RepresentativeFrame(frame_id="f-a", frame_order=0),
            path="/srv/a.py",
        ),
        Candidate(
            file_id="file-b",
            representative_frame=RepresentativeFrame(frame_id="f-b", frame_order=2),
            path="/srv/auth/handler.py",
        ),
    ]
    ranked = rank_candidates(signals, candidates=candidates, min_confidence=0.25)
    assert ranked[0].file_id == "file-a"

    assessments = compute_confidence_for_ranked(ranked, graph_context={"related_deployments": [{"id": "d1"}]})
    by_file = {r.file_id: a.confidence for r, a in zip(ranked, assessments)}
    assert by_file["file-b"] > by_file["file-a"]
    assert ranked[0].file_id == "file-a"


def test_build_confidence_reasoning_includes_factors() -> None:
    text = build_confidence_reasoning(
        {
            "candidate": "/srv/auth/handler.py",
            "confidence": 0.91,
            "confidence_level": "high",
            "supporting_factors": ["Deployment occurred within 5 minutes of incident"],
            "contradicting_factors": [],
        }
    )
    assert "0.91" in text
    assert "high" in text
    assert "Deployment" in text
