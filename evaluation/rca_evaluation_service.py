"""
RCA evaluation metrics for the dashboard backend.

Aggregates Neo4j feedback and investigation graph data.
Does not modify RCA ranking or feedback APIs.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from evaluation.rca_evaluation_models import (
    ConfidenceLevelAccuracy,
    ConfidenceMetrics,
    FeedbackTrendPoint,
    RcaEvaluationSummary,
    ServiceAccuracyRow,
)
from feedback.feedback_learning_service import (
    get_most_confirmed_candidates,
    get_most_rejected_candidates,
)
from feedback.feedback_models import FeedbackType
from graph.neo4j_client import Neo4jClient

HIGH_CONFIDENCE_THRESHOLD = 0.75
MEDIUM_CONFIDENCE_THRESHOLD = 0.50
DEFAULT_TREND_DAYS = 30
DEFAULT_CANDIDATE_LIMIT = 10


def _round_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _confidence_level(score: float) -> str:
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if score >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def _get_investigation_store():
    from artifacts.investigation_store import LocalFileInvestigationStore

    base = os.environ.get("JIRA_INVESTIGATION_STORE_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        "jira_rca_investigations",
    )
    return LocalFileInvestigationStore(base)


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_confidence_in_value(value: Any, candidate_id: str) -> tuple[float | None, str | None]:
    if isinstance(value, dict):
        candidate = str(value.get("candidate") or value.get("file_id") or value.get("path") or "").strip()
        conf = _as_float(value.get("confidence") or value.get("evidence_confidence"))
        level = str(value.get("confidence_level") or "").strip().lower() or None
        if candidate and candidate_id and candidate == candidate_id and conf is not None:
            return conf, level
        assessment = value.get("confidence_assessment")
        if isinstance(assessment, dict):
            conf = _as_float(assessment.get("confidence"))
            level = str(assessment.get("confidence_level") or "").strip().lower() or None
            if conf is not None and (not candidate_id or candidate == candidate_id or not candidate):
                return conf, level
        for nested in value.values():
            found_conf, found_level = _find_confidence_in_value(nested, candidate_id)
            if found_conf is not None:
                return found_conf, found_level
    elif isinstance(value, list):
        for item in value:
            found_conf, found_level = _find_confidence_in_value(item, candidate_id)
            if found_conf is not None:
                return found_conf, found_level
    return None, None


def _resolve_feedback_confidence(
    row: dict[str, Any],
    *,
    store_record: dict[str, Any] | None,
) -> tuple[float, str]:
    node_conf = _as_float(row.get("confidence"))
    node_level = str(row.get("confidence_level") or "").strip().lower()
    if node_conf is not None:
        return node_conf, node_level or _confidence_level(node_conf)

    candidate_id = str(row.get("candidate_id") or "")
    if store_record:
        conf, level = _find_confidence_in_value(store_record, candidate_id)
        if conf is not None:
            return conf, level or _confidence_level(conf)

    return 0.0, "unknown"


def _fetch_feedback_rows(client: Neo4jClient) -> list[dict[str, Any]]:
    return client.execute_read(
        """
        MATCH (f:Feedback)
        RETURN f.feedback_id AS feedback_id,
               f.investigation_id AS investigation_id,
               f.candidate_id AS candidate_id,
               f.feedback_type AS feedback_type,
               f.created_at AS created_at,
               f.confidence AS confidence,
               f.confidence_level AS confidence_level
        ORDER BY f.created_at DESC
        """
    )


def _fetch_feedback_counts(client: Neo4jClient) -> dict[str, int]:
    rows = client.execute_read(
        """
        MATCH (f:Feedback)
        RETURN count(f) AS total,
               sum(CASE WHEN f.feedback_type = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmed,
               sum(CASE WHEN f.feedback_type = 'REJECTED' THEN 1 ELSE 0 END) AS rejected,
               sum(CASE WHEN f.feedback_type = 'OVERRIDDEN' THEN 1 ELSE 0 END) AS overridden
        """
    )
    row = rows[0] if rows else {}
    return {
        "total": int(row.get("total") or 0),
        "confirmed": int(row.get("confirmed") or 0),
        "rejected": int(row.get("rejected") or 0),
        "overridden": int(row.get("overridden") or 0),
    }


def _count_investigations(client: Neo4jClient) -> int:
    rows = client.execute_read("MATCH (i:Investigation) RETURN count(i) AS total")
    return int(rows[0].get("total") or 0) if rows else 0


def get_rca_evaluation_summary(client: Neo4jClient) -> RcaEvaluationSummary:
    counts = _fetch_feedback_counts(client)
    total = counts["total"]
    confirmed = counts["confirmed"]
    rejected = counts["rejected"]
    overridden = counts["overridden"]

    confidence_metrics = get_confidence_metrics(client)

    return RcaEvaluationSummary(
        total_investigations=_count_investigations(client),
        total_feedback_count=total,
        confirmed_count=confirmed,
        rejected_count=rejected,
        overridden_count=overridden,
        confirmation_rate=_round_rate(confirmed, total),
        rejection_rate=_round_rate(rejected, total),
        override_rate=_round_rate(overridden, total),
        average_confidence=confidence_metrics.average_confidence,
        high_confidence_accuracy=confidence_metrics.high_confidence_accuracy,
        most_confirmed_candidates=get_most_confirmed_candidates(client, limit=DEFAULT_CANDIDATE_LIMIT),
        most_rejected_candidates=get_most_rejected_candidates(client, limit=DEFAULT_CANDIDATE_LIMIT),
    )


def get_accuracy_by_service(client: Neo4jClient) -> list[ServiceAccuracyRow]:
    rows = client.execute_read(
        """
        MATCH (f:Feedback)
        OPTIONAL MATCH (i:Investigation {id: f.investigation_id})
        OPTIONAL MATCH (i)-[*1..5]-(s:Service)
        WITH f, coalesce(head(collect(DISTINCT s.name)), 'unknown') AS service_name
        RETURN service_name,
               count(f) AS total_feedback,
               sum(CASE WHEN f.feedback_type = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmed_count,
               sum(CASE WHEN f.feedback_type = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_count,
               sum(CASE WHEN f.feedback_type = 'OVERRIDDEN' THEN 1 ELSE 0 END) AS overridden_count
        ORDER BY total_feedback DESC, service_name ASC
        """
    )
    return [
        ServiceAccuracyRow(
            service_name=str(row.get("service_name") or "unknown"),
            total_feedback=int(row.get("total_feedback") or 0),
            confirmed_count=int(row.get("confirmed_count") or 0),
            rejected_count=int(row.get("rejected_count") or 0),
            overridden_count=int(row.get("overridden_count") or 0),
            confirmation_rate=_round_rate(
                int(row.get("confirmed_count") or 0),
                int(row.get("total_feedback") or 0),
            ),
        )
        for row in rows
    ]


def get_confidence_metrics(client: Neo4jClient) -> ConfidenceMetrics:
    rows = _fetch_feedback_rows(client)
    if not rows:
        return ConfidenceMetrics()

    store = _get_investigation_store()
    store_cache: dict[str, dict[str, Any] | None] = {}
    enriched: list[tuple[float, str, str]] = []

    for row in rows:
        inv_id = str(row.get("investigation_id") or "").strip()
        if inv_id not in store_cache:
            try:
                store_cache[inv_id] = store.get_record(inv_id)
            except Exception:
                store_cache[inv_id] = None
        confidence, level = _resolve_feedback_confidence(row, store_record=store_cache.get(inv_id))
        feedback_type = str(row.get("feedback_type") or "")
        enriched.append((confidence, level, feedback_type))

    known_confidences = [conf for conf, level, _ in enriched if level != "unknown" or conf > 0]
    average_confidence = round(
        sum(known_confidences) / len(known_confidences),
        4,
    ) if known_confidences else 0.0

    high_rows = [(conf, ftype) for conf, level, ftype in enriched if conf >= HIGH_CONFIDENCE_THRESHOLD or level == "high"]
    high_confirmed = sum(1 for _, ftype in high_rows if ftype == FeedbackType.CONFIRMED.value)
    high_confidence_accuracy = _round_rate(high_confirmed, len(high_rows))

    buckets: dict[str, dict[str, int]] = {}
    for conf, level, ftype in enriched:
        bucket = level if level in {"high", "medium", "low"} else _confidence_level(conf)
        if bucket == "unknown":
            continue
        entry = buckets.setdefault(bucket, {"total": 0, "confirmed": 0})
        entry["total"] += 1
        if ftype == FeedbackType.CONFIRMED.value:
            entry["confirmed"] += 1

    accuracy_by_level = [
        ConfidenceLevelAccuracy(
            confidence_level=level,
            total_feedback=values["total"],
            confirmed_count=values["confirmed"],
            confirmation_rate=_round_rate(values["confirmed"], values["total"]),
        )
        for level, values in sorted(buckets.items(), key=lambda item: item[0])
    ]

    return ConfidenceMetrics(
        average_confidence=average_confidence,
        high_confidence_accuracy=high_confidence_accuracy,
        accuracy_by_confidence_level=accuracy_by_level,
    )


def get_recent_feedback_trend(
    client: Neo4jClient,
    *,
    days: int = DEFAULT_TREND_DAYS,
) -> list[FeedbackTrendPoint]:
    rows = client.execute_read(
        """
        MATCH (f:Feedback)
        WHERE f.created_at IS NOT NULL
        WITH substring(toString(f.created_at), 0, 10) AS day, f
        RETURN day,
               count(f) AS total_count,
               sum(CASE WHEN f.feedback_type = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmed_count,
               sum(CASE WHEN f.feedback_type = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_count,
               sum(CASE WHEN f.feedback_type = 'OVERRIDDEN' THEN 1 ELSE 0 END) AS overridden_count
        ORDER BY day ASC
        """
    )
    trend = [
        FeedbackTrendPoint(
            date=str(row.get("day") or ""),
            total_count=int(row.get("total_count") or 0),
            confirmed_count=int(row.get("confirmed_count") or 0),
            rejected_count=int(row.get("rejected_count") or 0),
            overridden_count=int(row.get("overridden_count") or 0),
        )
        for row in rows
        if row.get("day")
    ]
    if days <= 0 or len(trend) <= days:
        return trend
    return trend[-days:]
