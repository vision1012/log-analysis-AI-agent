"""Tests for alert ↔ PagerDuty incident correlator."""

from __future__ import annotations

import pytest

from mcp.context.alert_incident_correlator import (
    correlate_alert_incident,
    correlate_alert_incident_and_attach_metadata,
)
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.datadog_models import AlertEvent
from mcp.schemas.pagerduty_models import (
    PagerDutyEscalationEvent,
    PagerDutyIncidentEvent,
    PagerDutyTimelineEvent,
)


@pytest.fixture
def correlation_window(monkeypatch):
    monkeypatch.setenv("PAGERDUTY_CORRELATION_WINDOW_MINUTES", "30")


def _sample_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext(
        alert_events=[
            AlertEvent(
                alert_id="dd-alert-1",
                title="Critical error rate",
                message="error rate exceeded on auth-service",
                severity="critical",
                service="auth-service",
                status="triggered",
                triggered_at="2024-01-01T14:12:00Z",
            )
        ],
        pagerduty_incidents=[
            PagerDutyIncidentEvent(
                incident_id="INC123",
                incident_number=4567,
                title="High error rate on auth-service",
                description="Triggered by Datadog",
                service_name="auth-service",
                urgency="high",
                status="resolved",
                created_at="2024-01-01T14:13:00Z",
                resolved_at="2024-01-01T14:30:00Z",
                html_url="https://acme.pagerduty.com/incidents/INC123",
            )
        ],
        pagerduty_escalations=[
            PagerDutyEscalationEvent(
                escalation_policy_id="POL1",
                escalation_policy_name="Platform On-Call",
                incident_id="INC123",
                responder_name="Alex OnCall",
                responder_email="alex@example.com",
                assigned_at="2024-01-01T14:13:05Z",
            )
        ],
        pagerduty_timeline_events=[
            PagerDutyTimelineEvent(
                event_id="LE1",
                incident_id="INC123",
                event_type="acknowledge_log_entry",
                summary="Acknowledged by Alex",
                created_at="2024-01-01T14:14:00Z",
                actor_name="Alex OnCall",
            )
        ],
    )


def test_correlator_links_alert_to_incident(correlation_window):
    links = correlate_alert_incident(_sample_context())
    relations = {link.relation for link in links}
    assert "alert_to_pagerduty_incident" in relations
    assert "pagerduty_incident_to_escalation" in relations
    assert "pagerduty_incident_to_resolved" in relations
    assert "pagerduty_incident_to_service" in relations

    alert_link = next(l for l in links if l.relation == "alert_to_pagerduty_incident")
    assert alert_link.alert_id == "dd-alert-1"
    assert alert_link.incident_id == "INC123"
    assert alert_link.service_name == "auth-service"


def test_correlator_attaches_source_metadata(correlation_window):
    ctx = correlate_alert_incident_and_attach_metadata(_sample_context())
    pd_meta = [m for m in ctx.source_metadata if m.detail.startswith("pagerduty_links=")]
    assert len(pd_meta) == 1
    assert len(pd_meta[0].correlations) >= 3


def test_correlator_ignores_mismatched_service(correlation_window):
    ctx = _sample_context()
    ctx.pagerduty_incidents[0].service_name = "payments-api"
    links = correlate_alert_incident(ctx)
    alert_links = [l for l in links if l.relation == "alert_to_pagerduty_incident"]
    assert alert_links == []
