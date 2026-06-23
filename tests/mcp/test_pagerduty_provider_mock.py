"""Tests for PagerDuty MCP provider with mocked API responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mcp.config import MCPFetchParams
from mcp.providers.pagerduty_provider import PagerDutyProvider


@pytest.fixture
def pagerduty_env(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("PAGERDUTY_MCP_ENABLED", "true")
    monkeypatch.setenv("PAGERDUTY_API_TOKEN", "pd-token")
    monkeypatch.setenv("PAGERDUTY_SERVICE_ID", "PSVC123")


def _mock_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _urlopen_side_effect():
    def _side_effect(req, timeout=15):
        url = req.full_url
        if url.endswith("/abilities"):
            return _mock_response({"abilities": ["read_incidents"]})
        if "/incidents/" in url and "/log_entries" in url:
            return _mock_response(
                {
                    "log_entries": [
                        {
                            "id": "LE1",
                            "type": "acknowledge_log_entry",
                            "summary": "Acknowledged by on-call",
                            "created_at": "2024-01-01T14:14:00Z",
                            "agent": {"summary": "Alex OnCall"},
                        }
                    ]
                }
            )
        if "/incidents" in url:
            return _mock_response(
                {
                    "incidents": [
                        {
                            "id": "INC123",
                            "incident_number": 4567,
                            "title": "High error rate on auth-service",
                            "description": "Triggered by Datadog monitor",
                            "urgency": "high",
                            "status": "triggered",
                            "created_at": "2024-01-01T14:13:00Z",
                            "html_url": "https://acme.pagerduty.com/incidents/INC123",
                            "service": {"id": "PSVC123", "summary": "auth-service"},
                            "escalation_policy": {"id": "POL1", "summary": "Platform On-Call"},
                            "assignments": [
                                {
                                    "at": "2024-01-01T14:13:05Z",
                                    "assignee": {
                                        "summary": "Alex OnCall",
                                        "email": "alex@example.com",
                                    },
                                }
                            ],
                            "acknowledgements": [],
                        }
                    ]
                }
            )
        return _mock_response({})

    return _side_effect


@patch("mcp.providers.pagerduty_provider.request.urlopen")
def test_pagerduty_provider_fetch_normalizes_incidents(mock_urlopen, pagerduty_env):
    mock_urlopen.side_effect = _urlopen_side_effect()

    provider = PagerDutyProvider()
    assert provider.is_enabled() is True
    assert provider.is_configured() is True

    ctx = provider.fetch(
        MCPFetchParams(
            ticket_key="OPS-20",
            service_name="auth-service",
            start_time="2024-01-01T14:00:00Z",
            end_time="2024-01-01T15:00:00Z",
        )
    )
    assert len(ctx.pagerduty_incidents) == 1
    incident = ctx.pagerduty_incidents[0]
    assert incident.incident_id == "INC123"
    assert incident.incident_number == 4567
    assert incident.service_name == "auth-service"
    assert incident.urgency == "high"
    assert incident.status == "triggered"

    assert len(ctx.pagerduty_escalations) == 1
    assert ctx.pagerduty_escalations[0].responder_name == "Alex OnCall"
    assert ctx.pagerduty_escalations[0].escalation_policy_name == "Platform On-Call"

    assert len(ctx.pagerduty_timeline_events) == 1
    assert ctx.pagerduty_timeline_events[0].event_type == "acknowledge_log_entry"
    assert ctx.source_metadata[0].source == "pagerduty"


@patch("mcp.providers.pagerduty_provider.request.urlopen")
def test_pagerduty_provider_health_check_ok(mock_urlopen, pagerduty_env):
    mock_urlopen.return_value = _mock_response({"abilities": ["read_incidents"]})
    health = PagerDutyProvider().health_check()
    assert health.source == "pagerduty"
    assert health.enabled is True
    assert health.configured is True
    assert health.reachable is True


def test_pagerduty_provider_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("PAGERDUTY_MCP_ENABLED", "false")
    provider = PagerDutyProvider()
    assert provider.is_enabled() is False


def test_pagerduty_provider_not_configured_without_token(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("PAGERDUTY_MCP_ENABLED", "true")
    monkeypatch.delenv("PAGERDUTY_API_TOKEN", raising=False)
    provider = PagerDutyProvider()
    assert provider.is_configured() is False
    assert provider.fetch(MCPFetchParams(ticket_key="OPS-1")).pagerduty_incidents == []
