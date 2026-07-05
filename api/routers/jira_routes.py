"""JIRA ticket ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.deps.auth import get_current_user
from api.services.jira_service import JiraError, fetch_ticket_context, search_tickets
from api.utils.jira_http import http_exception_for_jira_integration
from schemas.jira import JiraTicketFetchResponse, JiraTicketSearchResponse

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/jira/tickets/search", response_model=JiraTicketSearchResponse)
async def search_jira_tickets(
    q: str | None = Query(
        None,
        max_length=200,
        description=(
            'Simple search; ticket keys (e.g. "ABC-123") map to issuekey JQL, '
            'otherwise text ~ "..." ORDER BY updated DESC'
        ),
    ),
    jql: str | None = Query(
        None,
        max_length=4000,
        description="Raw JQL. If set, takes precedence over q.",
    ),
    max_results: int = Query(25, ge=1, le=50, description="Max issues to return (capped at 50)."),
    workspace_id: str | None = Query(
        None,
        min_length=1,
        description="Workspace ID for DB-backed Jira connection (falls back to env when omitted).",
    ),
) -> JiraTicketSearchResponse:
    """Search JIRA issues for ticket picker UIs. Uses the same JIRA env config as fetch-by-key."""
    try:
        return search_tickets(q=q, jql=jql, max_results=max_results, workspace_id=workspace_id)
    except JiraError as exc:
        raise http_exception_for_jira_integration(exc) from exc


@router.get("/jira/tickets/{ticket_key}", response_model=JiraTicketFetchResponse)
async def get_jira_ticket_context(
    ticket_key: str = Path(..., min_length=3, description="JIRA ticket key, e.g. PROJ-123"),
    workspace_id: str | None = Query(
        None,
        min_length=1,
        description="Workspace ID for DB-backed Jira connection (falls back to env when omitted).",
    ),
) -> JiraTicketFetchResponse:
    """Fetch and normalize a JIRA ticket into backend ticket context."""
    try:
        return fetch_ticket_context(ticket_key, workspace_id=workspace_id)
    except JiraError as exc:
        raise http_exception_for_jira_integration(exc) from exc
