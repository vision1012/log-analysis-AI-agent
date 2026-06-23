"""Tests for first-class keyword RCA signals."""

from __future__ import annotations

from rca_engine.confidence_engine import compute_confidence_assessment
from rca_engine.ranking_model import rank_candidates
from rca_engine.signal_computation import (
    KEYWORD_ALIGNMENT_SIGNAL,
    KeywordSignal,
    align_keyword_signal_for_path,
    compute_log_keyword_signal,
    extract_keyword_signals,
)
from rca_engine.candidate_generator import Candidate, RepresentativeFrame


def test_compute_log_keyword_signal_classifies_categories() -> None:
    log = (
        "2024-01-01 ERROR auth-service timeout while connecting to postgres database\n"
        "Traceback: ConnectionRefusedError in handler.py"
    )
    signal = compute_log_keyword_signal(log)
    assert signal.matched_keywords
    assert signal.keyword_score > 0
    assert "Performance" in signal.keyword_categories
    assert "Database" in signal.keyword_categories or "Networking" in signal.keyword_categories


def test_align_keyword_signal_for_path_scores_matching_candidate() -> None:
    log = "ERROR auth handler timeout in auth_handler.py"
    log_signal = compute_log_keyword_signal(log)
    score, candidate_signal = align_keyword_signal_for_path(
        "/srv/auth/auth_handler.py",
        log_signal,
        log_files=["auth_handler.py"],
    )
    assert score > 0.4
    assert candidate_signal.keyword_score > 0
    assert isinstance(candidate_signal, KeywordSignal)


def test_extract_keyword_signals_backward_compatible() -> None:
    payload = extract_keyword_signals("ERROR timeout invalid token auth-service")
    assert "error_count" in payload
    assert "matched_keywords" in payload
    assert payload["keyword_categories"]


def test_keyword_alignment_affects_ranking_when_logs_present() -> None:
    base = {
        "top_frame_presence": 0.5,
        "frame_depth_penalty": 0.2,
        "last_touch_recency": 0.4,
        "deploy_proximity": 0.0,
        "deploy_recency_rank": 0.0,
        "historical_recurrence": 0.0,
        "resolution_quality": 0.5,
        "spike_correlation_strength": 0.0,
        "trace_completeness": 0.8,
        "file_touch_sparsity": 0.3,
        KEYWORD_ALIGNMENT_SIGNAL: 0.0,
    }
    signals = {
        "file-a": dict(base),
        "file-b": {**base, KEYWORD_ALIGNMENT_SIGNAL: 0.9},
    }
    ranked = rank_candidates(
        signals,
        candidates=[
            Candidate(
                file_id="file-a",
                representative_frame=RepresentativeFrame(frame_id="f1", frame_order=0),
                path="/srv/a.py",
            ),
            Candidate(
                file_id="file-b",
                representative_frame=RepresentativeFrame(frame_id="f2", frame_order=1),
                path="/srv/auth_handler.py",
            ),
        ],
        min_confidence=0.25,
    )
    assert ranked[0].file_id == "file-b"


def test_keyword_alignment_zero_preserves_relative_ranking_without_logs() -> None:
    base = {
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
        KEYWORD_ALIGNMENT_SIGNAL: 0.0,
    }
    signals = {
        "file-a": dict(base),
        "file-b": {
            **base,
            "top_frame_presence": 0.0,
            "last_touch_recency": 0.3,
        },
    }
    ranked = rank_candidates(
        signals,
        candidates=[
            Candidate(
                file_id="file-a",
                representative_frame=RepresentativeFrame(frame_id="f1", frame_order=0),
                path="/srv/a.py",
            ),
            Candidate(
                file_id="file-b",
                representative_frame=RepresentativeFrame(frame_id="f2", frame_order=2),
                path="/srv/b.py",
            ),
        ],
        min_confidence=0.25,
    )
    assert ranked[0].file_id == "file-a"


def test_confidence_engine_keyword_factors() -> None:
    strong = compute_confidence_assessment(
        candidate_path="/srv/auth/handler.py",
        signal_scores={KEYWORD_ALIGNMENT_SIGNAL: 0.8},
        graph_context={"keyword_context": {"available": True}},
    )
    assert any("Strong keyword alignment" in factor for factor in strong.supporting_factors)

    weak = compute_confidence_assessment(
        candidate_path="/srv/other.py",
        signal_scores={KEYWORD_ALIGNMENT_SIGNAL: 0.0},
        graph_context={"keyword_context": {"available": True}},
    )
    assert any("No keyword alignment" in factor for factor in weak.contradicting_factors)
