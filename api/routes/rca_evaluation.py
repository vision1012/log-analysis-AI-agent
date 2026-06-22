"""RCA evaluation dashboard API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.deps.auth import get_current_user
from api.services.rca_evaluation_api_service import (
    fetch_confidence_metrics,
    fetch_feedback_trend,
    fetch_rca_evaluation_summary,
    fetch_service_accuracy,
)
from evaluation.rca_evaluation_service import DEFAULT_TREND_DAYS

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/evaluation/rca/summary")
async def get_rca_evaluation_summary_endpoint() -> dict[str, object]:
    """Return headline RCA quality metrics for the evaluation dashboard."""
    summary = fetch_rca_evaluation_summary()
    return {"summary": summary.model_dump()}


@router.get("/evaluation/rca/services")
async def get_rca_service_accuracy_endpoint() -> dict[str, object]:
    """Return confirmation rates grouped by related service."""
    rows = fetch_service_accuracy()
    return {"services": [row.model_dump() for row in rows]}


@router.get("/evaluation/rca/confidence")
async def get_rca_confidence_metrics_endpoint() -> dict[str, object]:
    """Return confidence-related RCA accuracy metrics."""
    metrics = fetch_confidence_metrics()
    return {"confidence": metrics.model_dump()}


@router.get("/evaluation/rca/trends")
async def get_rca_feedback_trend_endpoint(
    days: int = Query(
        DEFAULT_TREND_DAYS,
        ge=1,
        le=365,
        description="Number of recent days to include in the feedback trend.",
    ),
) -> dict[str, object]:
    """Return daily feedback volume and outcome trend."""
    trend = fetch_feedback_trend(days=days)
    return {"trend": [point.model_dump() for point in trend]}
