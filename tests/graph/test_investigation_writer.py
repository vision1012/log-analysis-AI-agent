"""Tests for InvestigationGraphWriter node and relationship persistence."""

from __future__ import annotations

from typing import Any

import pytest

from graph.investigation_writer import InvestigationGraphWriter
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.confluence_models import ArchitectureDocument, KnownIssueDocument, RunbookDocument
from mcp.schemas.datadog_models import AlertEvent, MetricEvent
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.jira_models import McpTicketContext
from mcp.schemas.kubernetes_models import ContainerEvent, PodEvent
from mcp.schemas.pagerduty_models import PagerDutyIncidentEvent


class _RecordingClient:
    def __init__(self) -> None:
        self.operations: list[tuple[str, dict[str, Any]]] = []

    def execute_write(self, query: str, parameters: dict[str, Any] | None = None) -> None:
        self.operations.append((query, parameters or {}))

    def execute_write_tx(self, operations: list[tuple[str, dict[str, Any]]]) -> None:
        self.operations.extend(operations)


def _sample_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext(
        ticket_context=McpTicketContext(
            issue_key="OPS-20",
            summary="auth-service error spike",
            status="Open",
            priority="High",
            url="https://example.atlassian.net/browse/OPS-20",
        ),
        pull_requests=[
            McpPullRequest(
                number=42,
                title="Fix auth timeout",
                state="merged",
                merged=True,
                url="https://github.com/org/repo/pull/42",
            )
        ],
        commits=[
            McpCommit(
                sha="abc123def456",
                message="Fix auth timeout",
                author="dev@example.com",
                committed_at="2024-01-01T10:00:00Z",
            )
        ],
        build_events=[
            BuildEvent(
                build_id="build-1",
                build_number=101,
                status="SUCCESS",
                commit_sha="abc123def456",
                branch="main",
            )
        ],
        deployment_events=[
            DeploymentEvent(
                deployment_id="dep-1",
                environment="prod",
                status="SUCCESS",
                commit_sha="abc123def456",
                deployed_at="2024-01-01T11:00:00Z",
            )
        ],
        metric_events=[
            MetricEvent(
                metric_name="error_rate",
                service="auth-service",
                value=12.5,
                severity="high",
                timestamp="2024-01-01T12:00:00Z",
            )
        ],
        alert_events=[
            AlertEvent(
                alert_id="alert-1",
                title="High error rate",
                service="auth-service",
                severity="critical",
                triggered_at="2024-01-01T12:05:00Z",
            )
        ],
        pod_events=[
            PodEvent(
                pod_name="auth-service-abc",
                namespace="prod",
                node_name="node-1",
                status="Running",
                restart_count=2,
                reason="CrashLoopBackOff",
            )
        ],
        container_events=[
            ContainerEvent(
                container_name="auth",
                pod_name="auth-service-abc",
                status="Waiting",
                reason="CrashLoopBackOff",
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
                created_at="2024-01-01T12:10:00Z",
            )
        ],
        runbook_documents=[
            RunbookDocument(
                document_id="RB1",
                title="auth-service Runbook",
                space_key="OPS",
                url="https://example.atlassian.net/wiki/RB1",
                service_name="auth-service",
                summary="Rollback steps",
            )
        ],
        known_issue_documents=[
            KnownIssueDocument(
                document_id="KI1",
                title="Known OOM on auth-service",
                space_key="OPS",
                url="https://example.atlassian.net/wiki/KI1",
                affected_service="auth-service",
                error_keywords=["oom"],
                workaround="Increase memory",
            )
        ],
        architecture_documents=[
            ArchitectureDocument(
                document_id="AR1",
                title="auth-service Architecture",
                space_key="OPS",
                url="https://example.atlassian.net/wiki/AR1",
                service_name="auth-service",
                summary="AuthService overview",
            )
        ],
    )


def test_investigation_writer_persists_nodes_and_relationships() -> None:
    client = _RecordingClient()
    writer = InvestigationGraphWriter(client)
    counts = writer.write_investigation_context("inv-1", _sample_context(), ticket_key="OPS-20")

    assert counts["nodes"] > 0
    assert counts["relationships"] > 0
    assert client.operations

    queries = "\n".join(q for q, _ in client.operations)
    assert "Investigation" in queries
    assert "JiraTicket" in queries
    assert "PullRequest" in queries
    assert "Commit" in queries
    assert "Build" in queries
    assert "Deployment" in queries
    assert "MetricEvent" in queries
    assert "AlertEvent" in queries
    assert "PagerDutyIncident" in queries
    assert "Pod" in queries
    assert "Container" in queries
    assert "Runbook" in queries
    assert "KnownIssue" in queries
    assert "ArchitectureDocument" in queries
    assert "HAS_JIRA_TICKET" in queries
    assert "HAS_COMMIT" in queries
    assert "TRIGGERED_BUILD" in queries
    assert "PRODUCED_DEPLOYMENT" in queries
    assert "OBSERVED_METRIC" in queries
    assert "TRIGGERED_ALERT" in queries
    assert "ESCALATED_TO" in queries
    assert "AFFECTED_POD" in queries
    assert "HAS_CONTAINER" in queries
    assert "HAS_RUNBOOK" in queries
    assert "MATCHES_KNOWN_ISSUE" in queries
    assert "HAS_ARCHITECTURE_DOC" in queries


def test_investigation_writer_uses_stable_commit_sha() -> None:
    client = _RecordingClient()
    writer = InvestigationGraphWriter(client)
    context = UnifiedInvestigationContext(
        commits=[McpCommit(sha="deadbeef", message="test", author="dev")]
    )
    writer.write_investigation_context("inv-2", context)

    params = [p for _, p in client.operations if p.get("sha") == "deadbeef"]
    assert params
