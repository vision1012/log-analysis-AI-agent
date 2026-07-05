"""Tests for Jira MCP provider runtime connection support."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mcp.config import MCPFetchParams
from mcp.providers.jira_provider import JiraProvider
from mcp.runtime_connection import ProviderRuntimeConnection


@pytest.fixture
def jira_env(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("JIRA_MCP_ENABLED", "true")


def _mock_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_jira_provider_uses_runtime_connection_instead_of_env(jira_env) -> None:
    runtime = ProviderRuntimeConnection(
        connection_id="conn-jira-1",
        workspace_id="team-a",
        provider="jira",
        base_url="https://workspace-jira.example.net",
        credentials={"email": "bot@example.com", "api_token": "db-token"},
        source="database",
    )
    provider = JiraProvider(runtime_connection=runtime)

    def _urlopen(req, timeout=15):
        url = req.full_url
        if "/myself" in url:
            return _mock_response({"accountId": "abc"})
        if "/issue/OPS-9" in url:
            return _mock_response(
                {
                    "key": "OPS-9",
                    "fields": {
                        "summary": "Auth outage",
                        "description": "Users cannot login",
                        "status": {"name": "Open"},
                        "priority": {"name": "High"},
                        "labels": ["auth"],
                        "comment": {"comments": []},
                        "issuelinks": [],
                    },
                }
            )
        raise AssertionError(f"unexpected url {url}")

    with patch("mcp.providers.jira_provider.request.urlopen", side_effect=_urlopen):
        context = provider.fetch(MCPFetchParams(ticket_key="OPS-9", workspace_id="team-a"))

    assert context.ticket_context is not None
    assert context.ticket_context.issue_key == "OPS-9"
    assert "connection=conn-jira-1" in (context.source_metadata[0].detail or "")


def test_jira_provider_falls_back_to_env_when_no_runtime(jira_env, monkeypatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://env-jira.example.net")
    monkeypatch.setenv("JIRA_EMAIL", "env@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "env-token")
    provider = JiraProvider()

    with patch("mcp.providers.jira_provider.fetch_ticket_context") as mock_fetch:
        from schemas.jira import JiraExtractedHints, JiraNormalizedTicket, JiraTicketFetchResponse

        mock_fetch.return_value = JiraTicketFetchResponse(
            ticket=JiraNormalizedTicket(ticket_key="OPS-1", summary="Issue"),
            hints=JiraExtractedHints(),
        )
        with patch("mcp.providers.jira_provider._fetch_issue_with_links", return_value={"fields": {"comment": {}, "issuelinks": []}}):
            provider.fetch(MCPFetchParams(ticket_key="OPS-1", workspace_id="team-a"))

    mock_fetch.assert_called_once_with("OPS-1", workspace_id="team-a")
