"""Tests for JIRA ticket search (JQL / text query)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.services.jira_service import JiraInvalidSearchError, search_tickets


def test_search_tickets_requires_q_or_jql() -> None:
    with pytest.raises(JiraInvalidSearchError):
        search_tickets()


@patch("api.services.jira_service._post_json_to_jira")
@patch(
    "api.services.jira_service._jira_config_from_env",
    return_value={
        "base_url": "https://example.atlassian.net",
        "email": "dev@example.com",
        "api_token": "token",
    },
)
def test_search_tickets_ticket_key_q_uses_issuekey_jql(_cfg: object, mock_post: object) -> None:
    mock_post.return_value = {
        "issues": [
            {
                "key": "LAAA-83",
                "fields": {
                    "summary": "Auth regression",
                    "status": {"name": "Open"},
                    "priority": {"name": "High"},
                    "labels": ["backend"],
                    "updated": "2026-04-07T10:00:00.000+0000",
                },
            }
        ],
        "total": 1,
    }
    out = search_tickets(q="LAAA-83")
    assert out.jql_used == "issuekey = LAAA-83"
    assert out.issues[0].ticket_key == "LAAA-83"
    mock_post.assert_called_once()
    body = mock_post.call_args[0][2]
    assert body["jql"] == "issuekey = LAAA-83"


@patch("api.services.jira_service._post_json_to_jira")
@patch(
    "api.services.jira_service._jira_config_from_env",
    return_value={
        "base_url": "https://example.atlassian.net",
        "email": "dev@example.com",
        "api_token": "token",
    },
)
def test_search_tickets_text_q_builds_jql(_cfg: object, mock_post: object) -> None:
    mock_post.return_value = {
        "issues": [
            {
                "key": "PROJ-1",
                "fields": {
                    "summary": "Auth failure in login",
                    "status": {"name": "Open"},
                    "priority": {"name": "High"},
                    "labels": ["sev1"],
                    "updated": "2026-04-07T10:00:00.000+0000",
                },
            }
        ],
        "total": 1,
    }
    out = search_tickets(q="auth failure")
    assert out.total == 1
    assert out.issues[0].ticket_key == "PROJ-1"
    assert out.issues[0].summary == "Auth failure in login"
    assert out.jql_used == 'text ~ "auth failure" ORDER BY updated DESC'
    mock_post.assert_called_once()
    body = mock_post.call_args[0][2]
    assert body["jql"] == out.jql_used


@patch("api.services.jira_service._post_json_to_jira")
@patch(
    "api.services.jira_service._jira_config_from_env",
    return_value={
        "base_url": "https://example.atlassian.net",
        "email": "dev@example.com",
        "api_token": "token",
    },
)
def test_search_tickets_jql_takes_precedence(_cfg: object, mock_post: object) -> None:
    mock_post.return_value = {"issues": [], "total": 0}
    jql = "project = PROJ ORDER BY updated DESC"
    out = search_tickets(q="ignored", jql=jql)
    assert out.jql_used == jql
    assert mock_post.call_args[0][2]["jql"] == jql
