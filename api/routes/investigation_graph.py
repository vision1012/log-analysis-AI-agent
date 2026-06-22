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
