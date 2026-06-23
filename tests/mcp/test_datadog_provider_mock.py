"""Tests for Datadog MCP provider with mocked API responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mcp.config import MCPFetchParams
from mcp.providers.datadog_provider import DatadogProvider


@pytest.fixture
def datadog_env(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("DATADOG_MCP_ENABLED", "true")
    monkeypatch.setenv("DATADOG_API_KEY", "dd-api-key")
    monkeypatch.setenv("DATADOG_APP_KEY", "dd-app-key")
    monkeypatch.setenv("DATADOG_SITE", "datadoghq.com")


def _mock_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _urlopen_side_effect(metrics_payload, events_payload, traces_payload, monitors_payload):
    def _side_effect(req, timeout=15):
        url = req.full_url
        if "/api/v1/query" in url:
            return _mock_response(metrics_payload)
        if "/api/v1/events" in url:
            return _mock_response(events_payload)
        if "/api/v2/spans/events/search" in url:
            return _mock_response(traces_payload)
        if "/api/v1/monitor" in url:
            return _mock_response(monitors_payload)
        return _mock_response({})

    return _side_effect


@patch("mcp.providers.datadog_provider.request.urlopen")
def test_datadog_provider_fetch_normalizes_observability(mock_urlopen, datadog_env):
    metrics_payload = {
        "series": [
            {
                "scope": "service:payments-api",
                "unit": "percent",
                "pointlist": [[1_704_067_200_000, 92.5]],
            }
        ]
    }
    events_payload = {
        "events": [
            {
                "id": "alert-99",
                "title": "High error rate on payments-api",
                "text": "error rate exceeded threshold",
                "priority": "high",
                "alert_type": "error",
                "date_happened": 1_704_067_280,
                "tags": ["service:payments-api"],
                "monitor_id": 1001,
            }
        ]
    }
    traces_payload = {
        "data": [
            {
                "id": "trace-abc",
                "attributes": {
                    "service": "payments-api",
                    "status": "error",
                    "timestamp": "2024-01-01T14:13:00Z",
                    "custom": {
                        "service": "payments-api",
                        "resource_name": "POST /charge",
                        "duration": 250.0,
                    },
                },
            }
        ]
    }
    monitors_payload = [{"id": 1001, "name": "payments error rate", "type": "metric alert", "tags": []}]

    mock_urlopen.side_effect = _urlopen_side_effect(
        metrics_payload, events_payload, traces_payload, monitors_payload
    )

    provider = DatadogProvider()
    assert provider.is_enabled() is True
    assert provider.is_configured() is True

    ctx = provider.fetch(
        MCPFetchParams(
            ticket_key="OPS-9",
            service_name="payments-api",
            start_time="2024-01-01T14:00:00Z",
            end_time="2024-01-01T15:00:00Z",
        )
    )

    assert len(ctx.metric_events) >= 1
    assert ctx.metric_events[0].metric_name == "cpu_usage"
    assert ctx.metric_events[0].service in {"", "payments-api"}

    assert len(ctx.alert_events) == 1
    assert ctx.alert_events[0].alert_id == "alert-99"
    assert "error rate" in ctx.alert_events[0].title.lower()

    assert len(ctx.trace_events) == 1
    assert ctx.trace_events[0].error_count == 1

    assert len(ctx.service_health_events) >= 1
    assert ctx.source_metadata[0].source == "datadog"


@patch("mcp.providers.datadog_provider.request.urlopen")
def test_datadog_provider_health_check_ok(mock_urlopen, datadog_env):
    mock_urlopen.return_value = _mock_response([])
    health = DatadogProvider().health_check()
    assert health.source == "datadog"
    assert health.enabled is True
    assert health.configured is True
    assert health.reachable is True


def test_datadog_provider_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("DATADOG_MCP_ENABLED", "false")
    provider = DatadogProvider()
    assert provider.is_enabled() is False


def test_datadog_provider_not_configured_without_keys(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("DATADOG_MCP_ENABLED", "true")
    for key in ("DATADOG_API_KEY", "DATADOG_APP_KEY"):
        monkeypatch.delenv(key, raising=False)
    provider = DatadogProvider()
    assert provider.is_configured() is False
    assert provider.fetch(MCPFetchParams(ticket_key="OPS-1")).metric_events == []
