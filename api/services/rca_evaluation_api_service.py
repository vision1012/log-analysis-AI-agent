"""API layer for RCA evaluation dashboard metrics."""

from __future__ import annotations

from evaluation.rca_evaluation_models import (
    ConfidenceMetrics,
    FeedbackTrendPoint,
    RcaEvaluationSummary,
    ServiceAccuracyRow,
)
from evaluation.rca_evaluation_service import (
    DEFAULT_TREND_DAYS,
    get_accuracy_by_service,
    get_confidence_metrics,
    get_rca_evaluation_summary,
    get_recent_feedback_trend,
)
from graph.neo4j_client import Neo4jClient


def _get_client() -> Neo4jClient:
    return Neo4jClient.from_env()


def _with_client(fn, *args, **kwargs):
    client = _get_client()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        return fn(client, *args, **kwargs)
    finally:
        if getattr(client, "_driver", None):
            client.close()


def fetch_rca_evaluation_summary() -> RcaEvaluationSummary:
    return _with_client(get_rca_evaluation_summary)


def fetch_service_accuracy() -> list[ServiceAccuracyRow]:
    return _with_client(get_accuracy_by_service)


def fetch_confidence_metrics() -> ConfidenceMetrics:
    return _with_client(get_confidence_metrics)


def fetch_feedback_trend(*, days: int = DEFAULT_TREND_DAYS) -> list[FeedbackTrendPoint]:
    return _with_client(get_recent_feedback_trend, days=days)
