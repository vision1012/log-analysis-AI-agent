"""Retrieval of persisted JIRA-first RCA investigation history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.deps.auth import get_current_user
from api.services.jira_investigation_service import (
    InvestigationNotFoundError,
    get_investigation,
    list_investigations,
)
from schemas.jira_investigations import JiraInvestigationDetailResponse, JiraInvestigationListResponse

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/jira/investigations", response_model=JiraInvestigationListResponse)
async def list_jira_investigations(
    limit: int = Query(50, ge=1, le=100, description="Page size (max 100)."),
    offset: int = Query(0, ge=0, description="Offset for pagination."),
) -> JiraInvestigationListResponse:
    """List past JIRA-first RCA investigations (newest first). Does not include raw logs."""
    return list_investigations(limit=limit, offset=offset)


@router.get("/jira/investigations/{investigation_id}", response_model=JiraInvestigationDetailResponse)
async def get_jira_investigation(
    investigation_id: str = Path(..., min_length=1, description="Investigation id from a prior run response."),
) -> JiraInvestigationDetailResponse:
    """Return one persisted investigation record (metadata and derived signals only; raw logs are not stored)."""
    try:
        return get_investigation(investigation_id)
    except InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "investigation_not_found", "message": str(exc)},
        ) from exc
