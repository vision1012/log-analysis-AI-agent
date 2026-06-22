"""Investigation graph visualization API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.deps.auth import get_current_user
from api.services.feedback_learning_api_service import fetch_investigation_feedback
from api.services.investigation_graph_service import (
    InvestigationGraphNotFoundError,
    fetch_investigation_graph,
    fetch_similar_investigations,
)
from api.services.investigation_timeline_api_service import fetch_investigation_timeline
from api.services.multi_agent_investigation_api_service import fetch_multi_agent_investigation_report
from graph.graph_visualization_service import MAX_DEPTH, MIN_DEPTH
from graph.similar_incident_service import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/investigations/{investigation_id}/graph")
async def get_investigation_graph_endpoint(
    investigation_id: str = Path(..., min_length=1, description="Investigation id"),
    depth: int = Query(
        2,
        ge=MIN_DEPTH,
        le=MAX_DEPTH,
        description="Traversal depth from Investigation root (1–3 hops).",
    ),
) -> dict[str, object]:
    """
    Return nodes and edges for visualizing the MCP investigation graph.

    Response shape: ``{"nodes": [...], "edges": [...]}``.
    """
    try:
        return fetch_investigation_graph(investigation_id, depth=depth)
    except InvestigationGraphNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "investigation_graph_not_found", "message": str(exc)},
        ) from exc


@router.get("/investigations/{investigation_id}/similar")
async def get_similar_investigations_endpoint(
    investigation_id: str = Path(..., min_length=1, description="Investigation id"),
    limit: int = Query(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Maximum number of similar investigations to return.",
    ),
) -> dict[str, object]:
    """Return historical investigations similar to the current investigation."""
    try:
        results = fetch_similar_investigations(investigation_id, limit=limit)
    except InvestigationGraphNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "investigation_graph_not_found", "message": str(exc)},
        ) from exc
    return {
        "similar_investigations": [item.model_dump() for item in results],
    }


@router.get("/investigations/{investigation_id}/feedback")
async def get_investigation_feedback_endpoint(
    investigation_id: str = Path(..., min_length=1, description="Investigation id"),
) -> dict[str, object]:
    """Return engineer feedback recorded for an investigation."""
    records = fetch_investigation_feedback(investigation_id)
    return {
        "investigation_id": investigation_id,
        "feedback": [record.model_dump() for record in records],
    }


@router.get("/investigations/{investigation_id}/timeline")
async def get_investigation_timeline_endpoint(
    investigation_id: str = Path(..., min_length=1, description="Investigation id"),
    from_ts: str | None = Query(
        None,
        alias="from",
        description="Include events at or after this ISO-8601 timestamp.",
    ),
    to_ts: str | None = Query(
        None,
        alias="to",
        description="Include events at or before this ISO-8601 timestamp.",
    ),
    event_type: str | None = Query(
        None,
        description="Filter to a single timeline event type (e.g. ALERT_TRIGGERED).",
    ),
) -> dict[str, object]:
    """Return a unified chronological timeline for the investigation."""
    try:
        events = fetch_investigation_timeline(
            investigation_id,
            from_ts=from_ts,
            to_ts=to_ts,
            event_type=event_type,
        )
    except InvestigationGraphNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "investigation_graph_not_found", "message": str(exc)},
        ) from exc
    return {
        "investigation_id": investigation_id,
        "events": [event.model_dump() for event in events],
    }


@router.post("/investigations/{investigation_id}/multi-agent")
async def run_multi_agent_investigation_endpoint(
    investigation_id: str = Path(..., min_length=1, description="Investigation id"),
) -> dict[str, object]:
    """Run specialized investigation agents and return a merged report."""
    try:
        report = fetch_multi_agent_investigation_report(investigation_id)
    except InvestigationGraphNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "investigation_graph_not_found", "message": str(exc)},
        ) from exc
    return {"report": report.model_dump()}
