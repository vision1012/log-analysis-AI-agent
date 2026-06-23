"""Tests for deployment ↔ observability correlator."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mcp.context.deployment_observability_correlator import (
    correlate_deployment_observability,
    correlate_deployment_observability_and_attach_metadata,
)
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.datadog_models import AlertEvent, MetricEvent, TraceEvent
from mcp.schemas.jenkins_models import DeploymentEvent


@pytest.fixture
def correlation_window(monkeypatch):
    monkeypatch.setenv("DATADOG_CORRELATION_WINDOW_MINUTES", "30")


def _sample_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext(
        deployment_events=[
            DeploymentEvent(
                deployment_id="jenkins-deploy:99:production",
                environment="production",
                status="SUCCESS",
                commit_sha="abc123",
                build_number=99,
                deployed_at="2024-01-01T14:10:00Z",
                deployment_url="https://jenkins/job/app/99/",
            )
        ],
        metric_events=[
            MetricEvent(
                metric_name="cpu_usage",
                service="payments-api",
                value=92.5,
                unit="percent",
                severity="critical",
                timestamp="2024-01-01T14:12:00Z",
            ),
            MetricEvent(
                metric_name="error_rate",
                service="payments-api",
                value=3.2,
                unit="per_second",
                severity="high",
                timestamp="2024-01-01T14:12:30Z",
            ),
        ],
        alert_events=[
            AlertEvent(
                alert_id="alert-77",
                title="Error rate spike",
                message="threshold exceeded",
                severity="high",
                service="payments-api",
                status="triggered",
                triggered_at="2024-01-01T14:13:00Z",
            )
        ],
        trace_events=[
            TraceEvent(
                trace_id="trace-fail-1",
                service="payments-api",
                endpoint="POST /charge",
                latency_ms=850.0,
                error_count=1,
                timestamp="2024-01-01T14:14:00Z",
            )
        ],
    )


def test_correlator_links_deployment_metric_alert_trace(correlation_window):
    links = correlate_deployment_observability(_sample_context())
    relations = {link.relation for link in links}
    assert "deployment_to_metric_spike" in relations
    assert "deployment_to_alert" in relations
    assert "deployment_to_trace_failure" in relations
    assert "metric_spike_to_alert" in relations

    dep_metric = next(l for l in links if l.relation == "deployment_to_metric_spike")
    assert dep_metric.metric_name in {"cpu_usage", "error_rate"}

    metric_alert = next(l for l in links if l.relation == "metric_spike_to_alert")
    assert metric_alert.alert_id == "alert-77"


def test_correlator_attaches_source_metadata(correlation_window):
    ctx = correlate_deployment_observability_and_attach_metadata(_sample_context())
    obs_meta = [m for m in ctx.source_metadata if m.detail.startswith("observability_links=")]
    assert len(obs_meta) == 1
    assert len(obs_meta[0].correlations) >= 4


def test_correlator_ignores_events_outside_window(correlation_window):
    ctx = _sample_context()
    ctx.metric_events[0].timestamp = "2024-01-01T16:00:00Z"
    links = correlate_deployment_observability(ctx)
    dep_metric = [l for l in links if l.relation == "deployment_to_metric_spike" and l.metric_name == "cpu_usage"]
    assert dep_metric == []
