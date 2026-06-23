"""Tests for investigation evidence coverage framework."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp.connection_models import MCPConnectionStatus
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.evidence_coverage import compute_evidence_coverage
from mcp.schemas.confluence_models import RunbookDocument
from mcp.schemas.datadog_models import AlertEvent, MetricEvent, TraceEvent
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.gitlab_models import McpGitLabCommit, McpMergeRequest
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.jira_models import McpTicketContext
from mcp.schemas.kubernetes_models import ContainerEvent, NodeEvent, PodEvent
from mcp.schemas.pagerduty_models import PagerDutyIncidentEvent


def _status(
    provider: str,
    *,
    configured: bool = True,
    healthy: bool = True,
) -> MCPConnectionStatus:
    return MCPConnectionStatus(
        provider=provider,  # type: ignore[arg-type]
        configured=configured,
        healthy=healthy,
        last_checked="2024-01-01T12:00:00Z",
        error_message=None,
    )


def _all_healthy_statuses() -> dict[str, MCPConnectionStatus]:
    providers = [
        "jira",
        "github",
        "gitlab",
        "jenkins",
        "datadog",
        "kubernetes",
        "pagerduty",
        "confluence",
    ]
    return {name: _status(name) for name in providers}


def test_empty_context_has_low_coverage() -> None:
    coverage = compute_evidence_coverage(
        UnifiedInvestigationContext(),
        connection_statuses=_all_healthy_statuses(),
    )

    assert coverage.available_source_count == 0
    assert coverage.missing_source_count == 8
    assert coverage.coverage_score == 0.0
    assert coverage.coverage_level == "low"
    assert coverage.available_sources == []
    assert len(coverage.missing_sources) == 8


def test_contribution_rules_detect_each_provider() -> None:
    statuses = _all_healthy_statuses()
    context = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(issue_key="OPS-1", summary="Outage"),
        pull_requests=[McpPullRequest(number=1, title="Fix")],
        commits=[McpCommit(sha="abc"), McpGitLabCommit(id="gl-1")],
        merge_requests=[McpMergeRequest(iid=2, title="MR")],
        build_events=[BuildEvent(build_id="b1", build_number=10)],
        deployment_events=[DeploymentEvent(deployment_id="d1", environment="prod")],
        alert_events=[AlertEvent(alert_id="a1", title="High errors")],
        metric_events=[MetricEvent(metric_name="latency", value=99.0)],
        trace_events=[TraceEvent(trace_id="t1", service="api")],
        pod_events=[PodEvent(pod_name="pod-1")],
        container_events=[ContainerEvent(container_name="c1")],
        node_events=[NodeEvent(node_name="node-1")],
        pagerduty_incidents=[PagerDutyIncidentEvent(incident_id="INC1", title="Incident")],
        runbook_documents=[RunbookDocument(document_id="rb-1", title="Runbook")],
    )

    coverage = compute_evidence_coverage(context, connection_statuses=statuses)

    assert coverage.available_source_count == 8
    assert coverage.missing_source_count == 0
    assert coverage.coverage_score == 1.0
    assert coverage.coverage_level == "high"
    for source in ("jira", "github", "gitlab", "jenkins", "datadog", "kubernetes", "pagerduty", "confluence"):
        assert coverage.source_details[source].contributed is True
        assert coverage.source_details[source].configured is True
        assert coverage.source_details[source].healthy is True


def test_pagerduty_configured_but_not_contributed() -> None:
    statuses = _all_healthy_statuses()
    context = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(issue_key="OPS-2", summary="Issue"),
        alert_events=[AlertEvent(alert_id="a1", title="Alert")],
    )

    coverage = compute_evidence_coverage(context, connection_statuses=statuses)

    assert "jira" in coverage.available_sources
    assert "datadog" in coverage.available_sources
    assert "pagerduty" in coverage.missing_sources
    assert coverage.source_details["pagerduty"].configured is True
    assert coverage.source_details["pagerduty"].healthy is True
    assert coverage.source_details["pagerduty"].contributed is False


@pytest.mark.parametrize(
    ("available_count", "expected_level"),
    [
        (0, "low"),
        (1, "low"),
        (2, "partial"),
        (4, "good"),
        (6, "high"),
        (8, "high"),
    ],
)
def test_coverage_levels(available_count: int, expected_level: str) -> None:
    statuses = _all_healthy_statuses()
    context = UnifiedInvestigationContext()
    if available_count >= 1:
        context = UnifiedInvestigationContext(ticket_context=McpTicketContext(issue_key="OPS-1", summary="x"))
    if available_count >= 2:
        context = UnifiedInvestigationContext(
            ticket_context=McpTicketContext(issue_key="OPS-1", summary="x"),
            pull_requests=[McpPullRequest(number=1, title="PR")],
        )
    if available_count >= 3:
        context = UnifiedInvestigationContext(
            ticket_context=McpTicketContext(issue_key="OPS-1", summary="x"),
            pull_requests=[McpPullRequest(number=1, title="PR")],
            merge_requests=[McpMergeRequest(iid=1, title="MR")],
        )
    if available_count >= 4:
        context = UnifiedInvestigationContext(
            ticket_context=McpTicketContext(issue_key="OPS-1", summary="x"),
            pull_requests=[McpPullRequest(number=1, title="PR")],
            merge_requests=[McpMergeRequest(iid=1, title="MR")],
            build_events=[BuildEvent(build_id="b1", build_number=1)],
        )
    if available_count >= 5:
        context = UnifiedInvestigationContext(
            ticket_context=McpTicketContext(issue_key="OPS-1", summary="x"),
            pull_requests=[McpPullRequest(number=1, title="PR")],
            merge_requests=[McpMergeRequest(iid=1, title="MR")],
            build_events=[BuildEvent(build_id="b1", build_number=1)],
            alert_events=[AlertEvent(alert_id="a1", title="Alert")],
        )
    if available_count >= 6:
        context = UnifiedInvestigationContext(
            ticket_context=McpTicketContext(issue_key="OPS-1", summary="x"),
            pull_requests=[McpPullRequest(number=1, title="PR")],
            merge_requests=[McpMergeRequest(iid=1, title="MR")],
            build_events=[BuildEvent(build_id="b1", build_number=1)],
            alert_events=[AlertEvent(alert_id="a1", title="Alert")],
            pod_events=[PodEvent(pod_name="pod-1")],
        )
    if available_count >= 7:
        context = UnifiedInvestigationContext(
            ticket_context=McpTicketContext(issue_key="OPS-1", summary="x"),
            pull_requests=[McpPullRequest(number=1, title="PR")],
            merge_requests=[McpMergeRequest(iid=1, title="MR")],
            build_events=[BuildEvent(build_id="b1", build_number=1)],
            alert_events=[AlertEvent(alert_id="a1", title="Alert")],
            pod_events=[PodEvent(pod_name="pod-1")],
            pagerduty_incidents=[PagerDutyIncidentEvent(incident_id="INC1", title="Incident")],
        )
    if available_count >= 8:
        context = UnifiedInvestigationContext(
            ticket_context=McpTicketContext(issue_key="OPS-1", summary="x"),
            pull_requests=[McpPullRequest(number=1, title="PR")],
            merge_requests=[McpMergeRequest(iid=1, title="MR")],
            build_events=[BuildEvent(build_id="b1", build_number=1)],
            alert_events=[AlertEvent(alert_id="a1", title="Alert")],
            pod_events=[PodEvent(pod_name="pod-1")],
            pagerduty_incidents=[PagerDutyIncidentEvent(incident_id="INC1", title="Incident")],
            runbook_documents=[RunbookDocument(document_id="rb-1", title="Runbook")],
        )

    coverage = compute_evidence_coverage(context, connection_statuses=statuses)
    assert coverage.available_source_count == available_count
    assert coverage.coverage_level == expected_level


@patch("mcp.evidence_coverage.validate_all_connections", side_effect=RuntimeError("connection check failed"))
def test_missing_connection_status_handled_gracefully(mock_validate) -> None:
    context = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(issue_key="OPS-3", summary="Issue"),
    )

    coverage = compute_evidence_coverage(context)

    assert coverage.available_sources == ["jira"]
    assert coverage.source_details["jira"].configured is False
    assert coverage.source_details["jira"].healthy is False
    assert coverage.source_details["jira"].contributed is True


def test_jenkins_does_not_count_gitlab_deployments() -> None:
    from mcp.schemas.gitlab_models import McpDeploymentEvent

    statuses = _all_healthy_statuses()
    context = UnifiedInvestigationContext(
        deployment_events=[McpDeploymentEvent(environment="prod", status="success")],
    )

    coverage = compute_evidence_coverage(context, connection_statuses=statuses)

    assert "gitlab" not in coverage.available_sources
    assert "jenkins" not in coverage.available_sources


def test_github_commits_without_pull_requests() -> None:
    statuses = _all_healthy_statuses()
    context = UnifiedInvestigationContext(commits=[McpCommit(sha="abc123")])

    coverage = compute_evidence_coverage(context, connection_statuses=statuses)

    assert "github" in coverage.available_sources
    assert coverage.source_details["github"].contributed is True
