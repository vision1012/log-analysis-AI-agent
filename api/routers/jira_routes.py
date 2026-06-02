"""JIRA ticket ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query, status

from api.services.jira_mock_tickets import get_mock_jira_ticket
from api.services.jira_service import JiraError, fetch_ticket_context, search_tickets
from api.utils.jira_http import http_exception_for_jira_integration
from schemas.jira import JiraTicketFetchResponse, JiraTicketSearchResponse, MockJiraTicketResponse

router = APIRouter()


@router.get("/jira/ticket/{ticket_key}", response_model=MockJiraTicketResponse)
async def get_mock_jira_ticket_endpoint(
    ticket_key: str = Path(..., min_length=3, description="Demo JIRA ticket key, e.g. LAAA-78"),
) -> MockJiraTicketResponse:
    """Return deterministic mock ticket data for RCA demo (no live JIRA call)."""
    ticket = get_mock_jira_ticket(ticket_key)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


@router.get("/jira/tickets/search", response_model=JiraTicketSearchResponse)
async def search_jira_tickets(
    q: str | None = Query(
        None,
        max_length=200,
        description="Simple text search; mapped to JQL: text ~ \"...\" ORDER BY updated DESC",
    ),
    jql: str | None = Query(
        None,
        max_length=4000,
        description="Raw JQL. If set, takes precedence over q.",
    ),
    max_results: int = Query(25, ge=1, le=50, description="Max issues to return (capped at 50)."),
) -> JiraTicketSearchResponse:
    """Search JIRA issues for ticket picker UIs. Uses the same JIRA env config as fetch-by-key."""
    try:
        return search_tickets(q=q, jql=jql, max_results=max_results)
    except JiraError as exc:
        raise http_exception_for_jira_integration(exc) from exc


@router.get("/jira/tickets/{ticket_key}", response_model=JiraTicketFetchResponse)
async def get_jira_ticket_context(
    ticket_key: str = Path(..., min_length=3, description="JIRA ticket key, e.g. PROJ-123"),
) -> JiraTicketFetchResponse:
    """Fetch and normalize a JIRA ticket into backend ticket context."""
    try:
        return fetch_ticket_context(ticket_key)
    except JiraError as exc:
        raise http_exception_for_jira_integration(exc) from exc
