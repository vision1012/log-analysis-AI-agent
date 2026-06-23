"""Tests for deterministic investigation narrative generation."""

from __future__ import annotations

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.confluence_models import KnownIssueDocument, RunbookDocument
from mcp.schemas.datadog_models import AlertEvent, MetricEvent
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.kubernetes_models import PodEvent
from mcp.schemas.pagerduty_models import PagerDutyIncidentEvent
from graphrag.narrative_generator import (
    attach_narrative_to_output,
    generate_investigation_narrative,
)


def _sample_unified_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext(
        pull_requests=[
            McpPullRequest(
                number=42,
                title="Fix auth timeout",
                merged=True,
                merged_at="2024-01-01T10:00:00Z",
            )
        ],
        commits=[
            McpCommit(
                sha="abc123def456",
                message="Fix auth timeout",
                committed_at="2024-01-01T10:05:00Z",
            )
        ],
        build_events=[
            BuildEvent(
                build_id="build-1",
                build_number=101,
                status="SUCCESS",
                commit_sha="abc123def456",
                completed_at="2024-01-01T10:30:00Z",
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
                metric_name="cpu_usage",
                service="auth-service",
                value=95.0,
                severity="high",
                timestamp="2024-01-01T11:30:00Z",
            )
        ],
        alert_events=[
            AlertEvent(
                alert_id="alert-1",
                title="High error rate",
                service="auth-service",
                severity="critical",
                triggered_at="2024-01-01T11:35:00Z",
            )
        ],
        pod_events=[
            PodEvent(
                pod_name="auth-service-abc",
                namespace="prod",
                reason="CrashLoopBackOff",
                restart_count=3,
                timestamp="2024-01-01T11:20:00Z",
            )
        ],
        pagerduty_incidents=[
            PagerDutyIncidentEvent(
                incident_id="INC123",
                incident_number=4567,
                title="High error rate on auth-service",
                service_name="auth-service",
                created_at="2024-01-01T11:40:00Z",
            )
        ],
        runbook_documents=[
            RunbookDocument(
                document_id="RB1",
                title="auth-service Runbook",
                service_name="auth-service",
                summary="Rollback auth-service deployment",
            )
        ],
        known_issue_documents=[
            KnownIssueDocument(
                document_id="KI1",
                title="Known OOM",
                affected_service="auth-service",
                workaround="Increase memory limits",
            )
        ],
    )


def _sample_graph_context() -> dict:
    return {
        "related_deployments": [
            {
                "deployment_id": "dep-1",
                "environment": "prod",
                "status": "SUCCESS",
                "commit_sha": "abc123def456",
                "deployed_at": "2024-01-01T11:00:00Z",
            }
        ],
        "related_alerts": [
            {
                "alert_id": "alert-1",
                "title": "High error rate",
                "service": "auth-service",
                "severity": "critical",
                "triggered_at": "2024-01-01T11:35:00Z",
            }
        ],
        "related_incidents": [
            {
                "incident_id": "INC123",
                "title": "High error rate on auth-service",
                "status": "triggered",
                "created_at": "2024-01-01T11:40:00Z",
            }
        ],
        "runbooks": [
            {
                "runbook_id": "RB1",
                "title": "auth-service Runbook",
                "summary": "Rollback auth-service deployment",
            }
        ],
        "known_issues": [
            {
                "known_issue_id": "KI1",
                "title": "Known OOM",
                "affected_service": "auth-service",
                "workaround": "Increase memory limits",
            }
        ],
        "related_commits": [
            {
                "sha": "abc123def456",
                "message": "Fix auth timeout",
                "committed_at": "2024-01-01T10:05:00Z",
            }
        ],
    }


def test_generate_investigation_narrative_builds_timeline_and_chain() -> None:
    narrative = generate_investigation_narrative(
        {
            "candidates": [
                {"rank": 1, "path": "/srv/auth/handler.py", "confidence": 0.82, "file_id": "f1"}
            ]
        },
        unified_context=_sample_unified_context(),
        graph_context=_sample_graph_context(),
    )

    assert narrative.timeline_events
    timestamps = [e.timestamp for e in narrative.timeline_events if e.timestamp]
    assert timestamps == sorted(timestamps)

    event_types = {e.event_type for e in narrative.timeline_events}
    assert "pr_merged" in event_types
    assert "build_completed" in event_types
    assert "deployment_started" in event_types
    assert "alert_fired" in event_types
    assert "pagerduty_incident_created" in event_types

    assert len(narrative.causal_chain) >= 5
    chain_types = [link.entity_type for link in narrative.causal_chain]
    assert chain_types[0] == "commit"
    assert "deployment" in chain_types
    assert chain_types[-1] == "incident"

    assert narrative.supporting_evidence
    assert any("Runbook" in item for item in narrative.supporting_evidence)
    assert narrative.remediation_candidates
    assert "0.82" in narrative.confidence_summary


def test_attach_narrative_to_output_adds_fields_without_changing_rca() -> None:
    narrative = generate_investigation_narrative(
        {"candidates": [{"rank": 1, "path": "/srv/auth/handler.py", "confidence": 0.7, "file_id": "f1"}]},
        graph_context=_sample_graph_context(),
    )
    base = {
        "anomaly_id": "an-1",
        "primary_candidate": {"rank": 1, "file_id": "f1", "path": "/srv/auth/handler.py", "confidence": 0.7},
        "ranked_hypotheses": [{"rank": 1, "file_id": "f1", "confidence": 0.7}],
        "explanation_summary": "summary",
    }
    out = attach_narrative_to_output(base, narrative)

    assert out["primary_candidate"]["file_id"] == "f1"
    assert out["ranked_hypotheses"][0]["rank"] == 1
    assert out["timeline"]
    assert out["causal_chain"]
    assert out["investigation_summary"]
    assert out["investigation_narrative"]["confidence_summary"]
