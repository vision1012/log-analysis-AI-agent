"""Tests for RCA evaluation dashboard service."""

from __future__ import annotations

from typing import Any

import pytest

from evaluation.rca_evaluation_models import ConfidenceMetrics, RcaEvaluationSummary
from evaluation.rca_evaluation_service import (
    get_accuracy_by_service,
    get_confidence_metrics,
    get_rca_evaluation_summary,
    get_recent_feedback_trend,
)


class _MockClient:
    def __init__(
        self,
        *,
        investigation_count: int = 0,
        feedback_counts: dict[str, int] | None = None,
        feedback_rows: list[dict[str, Any]] | None = None,
        service_rows: list[dict[str, Any]] | None = None,
        trend_rows: list[dict[str, Any]] | None = None,
        candidate_rows: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.investigation_count = investigation_count
        self.feedback_counts = feedback_counts or {
            "total": 0,
            "confirmed": 0,
            "rejected": 0,
            "overridden": 0,
        }
        self.feedback_rows = feedback_rows or []
        self.service_rows = service_rows or []
        self.trend_rows = trend_rows or []
        self.candidate_rows = candidate_rows or {"confirmed": [], "rejected": []}

    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "MATCH (i:Investigation) RETURN count(i)" in query:
            return [{"total": self.investigation_count}]
        if "sum(CASE WHEN f.feedback_type = 'CONFIRMED'" in query and "service_name" not in query and "day" not in query:
            return [
                {
                    "total": self.feedback_counts["total"],
                    "confirmed": self.feedback_counts["confirmed"],
                    "rejected": self.feedback_counts["rejected"],
                    "overridden": self.feedback_counts["overridden"],
                }
            ]
        if "f.confidence AS confidence" in query:
            return self.feedback_rows
        if "service_name" in query and "total_feedback" in query:
            return self.service_rows
        if "substring(toString(f.created_at), 0, 10) AS day" in query:
            return self.trend_rows
        if "feedback_type: 'CONFIRMED'" in query:
            return self.candidate_rows.get("confirmed", [])
        if "feedback_type: 'REJECTED'" in query:
            return self.candidate_rows.get("rejected", [])
        return []


def test_get_rca_evaluation_summary_empty_state() -> None:
    summary = get_rca_evaluation_summary(_MockClient(investigation_count=3))
    assert isinstance(summary, RcaEvaluationSummary)
    assert summary.total_investigations == 3
    assert summary.total_feedback_count == 0
    assert summary.confirmation_rate == 0.0
    assert summary.most_confirmed_candidates == []


def test_get_rca_evaluation_summary_with_feedback() -> None:
    client = _MockClient(
        investigation_count=5,
        feedback_counts={"total": 4, "confirmed": 2, "rejected": 1, "overridden": 1},
        feedback_rows=[
            {
                "feedback_id": "fb-1",
                "investigation_id": "inv-1",
                "candidate_id": "c1",
                "feedback_type": "CONFIRMED",
                "created_at": "2024-01-01T00:00:00Z",
                "confidence": 0.9,
                "confidence_level": "high",
            }
        ],
        candidate_rows={
            "confirmed": [{"candidate_id": "c1", "count": 2}],
            "rejected": [{"candidate_id": "c2", "count": 1}],
        },
    )
    summary = get_rca_evaluation_summary(client)
    assert summary.total_feedback_count == 4
    assert summary.confirmed_count == 2
    assert summary.confirmation_rate == 0.5
    assert summary.override_rate == 0.25
    assert summary.most_confirmed_candidates[0].candidate_id == "c1"
    assert summary.average_confidence == 0.9
    assert summary.high_confidence_accuracy == 1.0


def test_get_accuracy_by_service() -> None:
    rows = get_accuracy_by_service(
        _MockClient(
            service_rows=[
                {
                    "service_name": "auth-service",
                    "total_feedback": 3,
                    "confirmed_count": 2,
                    "rejected_count": 1,
                    "overridden_count": 0,
                }
            ]
        )
    )
    assert len(rows) == 1
    assert rows[0].service_name == "auth-service"
    assert rows[0].confirmation_rate == pytest.approx(0.6667, rel=1e-3)


def test_get_confidence_metrics_groups_by_level() -> None:
    metrics = get_confidence_metrics(
        _MockClient(
            feedback_rows=[
                {
                    "feedback_id": "fb-1",
                    "investigation_id": "inv-1",
                    "candidate_id": "c1",
                    "feedback_type": "CONFIRMED",
                    "created_at": "2024-01-01T00:00:00Z",
                    "confidence": 0.9,
                    "confidence_level": "high",
                },
                {
                    "feedback_id": "fb-2",
                    "investigation_id": "inv-2",
                    "candidate_id": "c2",
                    "feedback_type": "REJECTED",
                    "created_at": "2024-01-02T00:00:00Z",
                    "confidence": 0.55,
                    "confidence_level": "medium",
                },
            ]
        )
    )
    assert isinstance(metrics, ConfidenceMetrics)
    assert metrics.average_confidence == 0.725
    assert metrics.high_confidence_accuracy == 1.0
    levels = {row.confidence_level: row for row in metrics.accuracy_by_confidence_level}
    assert levels["high"].confirmed_count == 1
    assert levels["medium"].confirmed_count == 0


def test_get_recent_feedback_trend_limits_days() -> None:
    trend = get_recent_feedback_trend(
        _MockClient(
            trend_rows=[
                {"day": "2024-01-01", "total_count": 1, "confirmed_count": 1, "rejected_count": 0, "overridden_count": 0},
                {"day": "2024-01-02", "total_count": 2, "confirmed_count": 1, "rejected_count": 1, "overridden_count": 0},
                {"day": "2024-01-03", "total_count": 1, "confirmed_count": 0, "rejected_count": 0, "overridden_count": 1},
            ]
        ),
        days=2,
    )
    assert len(trend) == 2
    assert trend[0].date == "2024-01-02"
    assert trend[1].date == "2024-01-03"
