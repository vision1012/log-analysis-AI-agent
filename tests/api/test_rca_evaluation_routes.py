"""API route tests for RCA evaluation dashboard."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from evaluation.rca_evaluation_models import (
    ConfidenceLevelAccuracy,
    ConfidenceMetrics,
    FeedbackTrendPoint,
    RcaEvaluationSummary,
    ServiceAccuracyRow,
)
from feedback.feedback_models import CandidateFeedbackCount


def test_rca_evaluation_summary_endpoint() -> None:
    from api.routes.rca_evaluation import get_rca_evaluation_summary_endpoint

    summary = RcaEvaluationSummary(
        total_investigations=10,
        total_feedback_count=4,
        confirmed_count=2,
        rejected_count=1,
        overridden_count=1,
        confirmation_rate=0.5,
        rejection_rate=0.25,
        override_rate=0.25,
        average_confidence=0.82,
        high_confidence_accuracy=1.0,
        most_confirmed_candidates=[CandidateFeedbackCount(candidate_id="c1", count=2)],
        most_rejected_candidates=[],
    )
    with patch("api.routes.rca_evaluation.fetch_rca_evaluation_summary", return_value=summary):
        body = asyncio.run(get_rca_evaluation_summary_endpoint())

    assert body["summary"]["total_investigations"] == 10
    assert body["summary"]["confirmation_rate"] == 0.5
    assert body["summary"]["most_confirmed_candidates"][0]["candidate_id"] == "c1"


def test_rca_service_accuracy_endpoint() -> None:
    from api.routes.rca_evaluation import get_rca_service_accuracy_endpoint

    rows = [
        ServiceAccuracyRow(
            service_name="auth-service",
            total_feedback=3,
            confirmed_count=2,
            rejected_count=1,
            confirmation_rate=0.6667,
        )
    ]
    with patch("api.routes.rca_evaluation.fetch_service_accuracy", return_value=rows):
        body = asyncio.run(get_rca_service_accuracy_endpoint())

    assert len(body["services"]) == 1
    assert body["services"][0]["service_name"] == "auth-service"


def test_rca_confidence_metrics_endpoint() -> None:
    from api.routes.rca_evaluation import get_rca_confidence_metrics_endpoint

    metrics = ConfidenceMetrics(
        average_confidence=0.8,
        high_confidence_accuracy=0.9,
        accuracy_by_confidence_level=[
            ConfidenceLevelAccuracy(
                confidence_level="high",
                total_feedback=2,
                confirmed_count=2,
                confirmation_rate=1.0,
            )
        ],
    )
    with patch("api.routes.rca_evaluation.fetch_confidence_metrics", return_value=metrics):
        body = asyncio.run(get_rca_confidence_metrics_endpoint())

    assert body["confidence"]["average_confidence"] == 0.8
    assert body["confidence"]["accuracy_by_confidence_level"][0]["confidence_level"] == "high"


def test_rca_feedback_trend_endpoint() -> None:
    from api.routes.rca_evaluation import get_rca_feedback_trend_endpoint

    trend = [
        FeedbackTrendPoint(
            date="2024-01-01",
            total_count=2,
            confirmed_count=1,
            rejected_count=1,
        )
    ]
    with patch("api.routes.rca_evaluation.fetch_feedback_trend", return_value=trend):
        body = asyncio.run(get_rca_feedback_trend_endpoint(days=30))

    assert len(body["trend"]) == 1
    assert body["trend"][0]["date"] == "2024-01-01"
