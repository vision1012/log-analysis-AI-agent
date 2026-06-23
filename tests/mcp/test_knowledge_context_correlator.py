"""Tests for Confluence knowledge context correlator."""

from __future__ import annotations

from mcp.context.knowledge_context_correlator import (
    correlate_knowledge,
    correlate_knowledge_and_attach_metadata,
)
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.confluence_models import ArchitectureDocument, KnownIssueDocument, RunbookDocument
from mcp.schemas.datadog_models import AlertEvent
from mcp.schemas.jira_models import McpTicketContext
from mcp.schemas.kubernetes_models import PodEvent
from mcp.schemas.pagerduty_models import PagerDutyIncidentEvent


def _sample_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext(
        ticket_context=McpTicketContext(
            issue_key="OPS-20",
            summary="auth-service error rate spike",
            description="OOM and timeout errors on auth-service",
            labels=["incident"],
        ),
        alert_events=[
            AlertEvent(
                alert_id="dd-alert-1",
                title="Critical error rate",
                message="OOM error on auth-service",
                severity="critical",
                service="auth-service",
                status="triggered",
                triggered_at="2024-01-01T14:12:00Z",
            )
        ],
        pod_events=[
            PodEvent(
                pod_name="auth-service-abc",
                namespace="prod",
                reason="OOMKilled",
                status="Failed",
                restart_count=3,
            )
        ],
        pagerduty_incidents=[
            PagerDutyIncidentEvent(
                incident_id="INC123",
                incident_number=4567,
                title="High error rate on auth-service",
                service_name="auth-service",
                urgency="high",
                status="triggered",
                created_at="2024-01-01T14:13:00Z",
            )
        ],
        runbook_documents=[
            RunbookDocument(
                document_id="RB1",
                title="auth-service Incident Response SOP",
                space_key="OPS",
                url="https://acme.atlassian.net/wiki/spaces/OPS/pages/RB1",
                service_name="auth-service",
                summary="Incident response and rollback steps",
                labels=["sop", "incident"],
            )
        ],
        known_issue_documents=[
            KnownIssueDocument(
                document_id="KI1",
                title="Known issue: OOM on auth-service",
                space_key="OPS",
                url="https://acme.atlassian.net/wiki/spaces/OPS/pages/KI1",
                affected_service="auth-service",
                error_keywords=["oom", "error"],
                workaround="Increase memory limits",
                severity="high",
            )
        ],
        architecture_documents=[
            ArchitectureDocument(
                document_id="AR1",
                title="auth-service Architecture",
                space_key="OPS",
                url="https://acme.atlassian.net/wiki/spaces/OPS/pages/AR1",
                service_name="auth-service",
                summary="AuthService and TokenCache overview",
                components=["AuthService", "TokenCache"],
            )
        ],
    )


def test_correlator_links_service_runbook_and_architecture():
    links = correlate_knowledge(_sample_context())
    relations = {link.relation for link in links}
    assert "service_to_runbook" in relations
    assert "service_to_architecture_doc" in relations
    assert "alert_to_known_issue" in relations
    assert "pod_error_to_known_issue" in relations
    assert "incident_to_sop" in relations


def test_correlator_attaches_source_metadata():
    ctx = correlate_knowledge_and_attach_metadata(_sample_context())
    knowledge_meta = [m for m in ctx.source_metadata if m.detail.startswith("knowledge_links=")]
    assert len(knowledge_meta) == 1
    assert len(knowledge_meta[0].correlations) >= 4


def test_correlator_ignores_unrelated_known_issue():
    ctx = _sample_context()
    ctx.known_issue_documents[0].affected_service = "payments-api"
    ctx.known_issue_documents[0].error_keywords = ["invoice"]
    links = correlate_knowledge(ctx)
    alert_links = [l for l in links if l.relation == "alert_to_known_issue"]
    assert alert_links == []
