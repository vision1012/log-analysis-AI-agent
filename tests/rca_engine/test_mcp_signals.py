"""Tests for MCP-derived RCA signal computation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from rca_engine.signal_computation import (
    _deployment_proximity_bucket,
    compute_mcp_signals,
)


def test_deployment_proximity_bucket_mapping() -> None:
    assert _deployment_proximity_bucket(3.0)[0] == "0_5"
    assert _deployment_proximity_bucket(10.0)[0] == "5_15"
    assert _deployment_proximity_bucket(20.0)[0] == "15_30"
    assert _deployment_proximity_bucket(45.0)[0] == "beyond_30"


def test_compute_mcp_signals_produces_breakdown(monkeypatch) -> None:
    monkeypatch.setenv("MCP_RCA_SIGNALS_ENABLED", "true")
    anomaly_ts = 1_704_110_400.0  # 2024-01-01T12:00:00Z
    graph_context = {
        "related_deployments": [
            {
                "deployment_id": "dep-1",
                "environment": "prod",
                "deployed_at": "2024-01-01T11:57:00Z",
            }
        ],
        "related_alerts": [
            {
                "alert_id": "alert-1",
                "severity": "critical",
                "title": "High error rate",
                "triggered_at": "2024-01-01T11:58:00Z",
            },
            {
                "alert_id": "alert-2",
                "severity": "warning",
                "title": "Elevated latency",
                "triggered_at": "2024-01-01T11:59:00Z",
            },
        ],
        "related_incidents": [
            {
                "incident_id": "INC1",
                "urgency": "high",
                "title": "Incident",
                "created_at": "2024-01-01T12:05:00Z",
            }
        ],
        "known_issues": [
            {
                "known_issue_id": "KI1",
                "title": "auth handler timeout",
                "affected_service": "auth-service",
                "error_keywords": ["timeout"],
            }
        ],
        "previous_investigations": [
            {"investigation_id": "inv-old", "similarity_score": 0.8}
        ],
    }

    client = MagicMock()
    client.execute_read.return_value = [{"prior_count": 2}]

    signals, breakdowns = compute_mcp_signals(
        file_ids=["file-1"],
        path_by_file={"file-1": "/srv/auth/handler.py"},
        anomaly_ts=anomaly_ts,
        service_ref="auth-service",
        mcp_graph_context=graph_context,
        graph_client=client,
        investigation_id="inv-1",
    )

    assert signals["file-1"]["deployment_proximity_mcp"] == 1.0
    assert signals["file-1"]["alert_correlation"] == 1.0
    assert signals["file-1"]["incident_severity"] == 1.0
    assert signals["file-1"]["known_issue_match"] == 1.0
    assert signals["file-1"]["historical_investigation"] >= 0.8

    bd = breakdowns["file-1"]
    assert bd.get("deployment_proximity", 0) > 0
    assert bd.get("alert_correlation", 0) > 0
    assert bd.get("incident_severity", 0) > 0
    assert bd.get("known_issue_match", 0) > 0
    assert bd.get("historical_investigation", 0) > 0


def test_compute_mcp_signals_disabled_returns_empty(monkeypatch) -> None:
    monkeypatch.setenv("MCP_RCA_SIGNALS_ENABLED", "false")
    from rca_engine import mcp_signal_config

    assert mcp_signal_config.mcp_rca_signals_enabled() is False
