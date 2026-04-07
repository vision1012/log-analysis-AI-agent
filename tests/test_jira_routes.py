"""Endpoint tests for JIRA ticket context route error mapping."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.services.jira_service import JiraAuthError, JiraConfigError, JiraNotFoundError
from schemas.jira import JiraExtractedHints, JiraNormalizedTicket, JiraTicketFetchResponse


def test_get_jira_ticket_context_success() -> None:
    payload = JiraTicketFetchResponse(
        ticket=JiraNormalizedTicket(
            ticket_id="1001",
            ticket_key="PROJ-12",
            summary="summary",
            description="desc",
            comments_text="comments",
            status="In Progress",
            priority="High",
            labels=["sev1"],
            created_at="2026-01-01T00:00:00.000+0000",
            updated_at="2026-01-02T00:00:00.000+0000",
            url="https://example.atlassian.net/browse/PROJ-12",
            cleaned_text_body="summary desc comments",
        ),
        hints=JiraExtractedHints(labels=["sev1"]),
    )

    with patch("api.routers.jira_routes.fetch_ticket_context", return_value=payload):
        client = TestClient(app)
        r = client.get("/api/v1/jira/tickets/PROJ-12")
    assert r.status_code == 200
    data = r.json()
    assert data["ticket"]["ticket_key"] == "PROJ-12"
    assert data["hints"]["labels"] == ["sev1"]


def test_get_jira_ticket_context_maps_config_error() -> None:
    with patch("api.routers.jira_routes.fetch_ticket_context", side_effect=JiraConfigError("missing config")):
        client = TestClient(app)
        r = client.get("/api/v1/jira/tickets/PROJ-12")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "jira_config_missing"


def test_get_jira_ticket_context_maps_auth_error() -> None:
    with patch("api.routers.jira_routes.fetch_ticket_context", side_effect=JiraAuthError("bad auth")):
        client = TestClient(app)
        r = client.get("/api/v1/jira/tickets/PROJ-12")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "jira_auth_failed"


def test_get_jira_ticket_context_maps_not_found_error() -> None:
    with patch("api.routers.jira_routes.fetch_ticket_context", side_effect=JiraNotFoundError("missing ticket")):
        client = TestClient(app)
        r = client.get("/api/v1/jira/tickets/PROJ-12")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "jira_ticket_not_found"
