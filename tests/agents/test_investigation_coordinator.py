"""Tests for multi-agent investigation coordinator and agents."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agents.agent_models import AgentFinding, AgentInvestigationContext
from agents.base_agent import BaseAgent
from agents.deployment_agent import DeploymentAgent
from agents.infrastructure_agent import InfrastructureAgent
from agents.investigation_coordinator import (
    build_multi_agent_report,
    default_agents,
    run_agents,
    run_multi_agent_investigation,
)
from agents.rca_agent import RCAAgent
from agents.timeline_agent import TimelineAgent
from graph.retrieval_models import GraphAlertRecord, GraphDeploymentRecord, SimilarInvestigation
from investigation.timeline_models import InvestigationTimelineEvent


class _StubAgent(BaseAgent):
    def __init__(self, name: str, summary: str) -> None:
        self.name = name
        self._summary = summary

    def investigate(self, context: AgentInvestigationContext) -> AgentFinding:
        return AgentFinding(
            agent_name=self.name,
            summary=self._summary,
            key_observations=[f"context={context.investigation_id}"],
            confidence=0.5,
        )


class _MockClient:
    def __init__(self, *, exists: bool = True) -> None:
        self.exists = exists

    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "RETURN i.id AS id LIMIT 1" in query:
            return [{"id": parameters.get("investigation_id")}] if self.exists else []
        if "labels(n)" in query or "UNWIND" in query or "shared_keys" in query:
            return []
        if "Build" in query:
            return [
                {
                    "build_id": "build-1",
                    "build_number": 10,
                    "status": "SUCCESS",
                    "branch": "main",
                    "commit_sha": "abc123",
                    "started_at": "2024-01-01T09:00:00Z",
                    "completed_at": "2024-01-01T09:10:00Z",
                    "build_url": "",
                }
            ]
        return []


def _sample_context() -> AgentInvestigationContext:
    return AgentInvestigationContext(
        investigation_id="inv-1",
        ticket_key="OPS-1",
        service_name="auth-service",
        timeline_events=[
            InvestigationTimelineEvent(
                event_id="e1",
                timestamp="2024-01-01T09:35:00Z",
                event_type="DEPLOYMENT_COMPLETED",
                source="Jenkins",
                title="Deployment completed",
            ),
            InvestigationTimelineEvent(
                event_id="e2",
                timestamp="2024-01-01T09:45:00Z",
                event_type="ALERT_TRIGGERED",
                source="Datadog",
                title="Auth error rate critical",
                severity="critical",
            ),
            InvestigationTimelineEvent(
                event_id="e3",
                timestamp="2024-01-01T09:50:00Z",
                event_type="OOM_KILLED",
                source="Kubernetes",
                title="OOM killed: auth",
                severity="high",
            ),
        ],
        deployments=[
            GraphDeploymentRecord(
                deployment_id="dep-1",
                environment="prod",
                status="SUCCESS",
                commit_sha="abc123",
                deployed_at="2024-01-01T09:35:00Z",
                service_name="auth-service",
                investigation_id="inv-1",
            )
        ],
        builds=[{"build_number": 10, "status": "SUCCESS"}],
        alerts=[
            GraphAlertRecord(
                alert_id="alert-1",
                title="Auth error rate critical",
                severity="critical",
                service="auth-service",
                triggered_at="2024-01-01T09:45:00Z",
                investigation_id="inv-1",
            )
        ],
        similar_investigations=[
            SimilarInvestigation(
                investigation_id="inv-old",
                similarity_score=0.72,
                root_cause="/srv/auth/handler.py",
            )
        ],
        store_record={
            "run_status": "completed",
            "relationship_ready_bundle": {"rca_target_file": "/srv/auth/handler.py"},
            "confidence_assessments": [
                {
                    "candidate": "/srv/auth/handler.py",
                    "confidence": 0.88,
                    "confidence_level": "high",
                    "supporting_factors": ["deployment_proximity"],
                }
            ],
        },
    )


def test_default_agents_includes_all_specialists() -> None:
    names = {agent.name for agent in default_agents()}
    assert names == {"timeline", "deployment", "infrastructure", "incident", "knowledge", "rca"}


def test_run_agents_executes_independently() -> None:
    context = _sample_context()
    findings = run_agents(
        context,
        agents=[
            _StubAgent("timeline", "timeline done"),
            _StubAgent("deployment", "deployment done"),
        ],
    )
    assert findings["timeline"].summary == "timeline done"
    assert findings["deployment"].summary == "deployment done"
    assert findings["timeline"].key_observations == ["context=inv-1"]


def test_timeline_agent_detects_deploy_before_alert() -> None:
    finding = TimelineAgent().investigate(_sample_context())
    assert finding.suspicious_items
    assert "deployment_precedes_alert" in finding.correlations


def test_infrastructure_agent_detects_oom() -> None:
    finding = InfrastructureAgent().investigate(_sample_context())
    assert "oom_killed" in finding.correlations


def test_deployment_agent_reports_build_and_deploy() -> None:
    finding = DeploymentAgent().investigate(_sample_context())
    assert finding.evidence["build_count"] == 1
    assert finding.evidence["deployment_count"] == 1


def test_rca_agent_reads_store_without_running_rca() -> None:
    finding = RCAAgent().investigate(_sample_context())
    assert "/srv/auth/handler.py" in finding.summary
    assert finding.confidence == 0.88


def test_build_multi_agent_report_merges_findings() -> None:
    context = _sample_context()
    findings = {
        "timeline": AgentFinding(agent_name="timeline", summary="t", confidence=0.8),
        "deployment": AgentFinding(agent_name="deployment", summary="d", confidence=0.6),
        "infrastructure": AgentFinding(agent_name="infrastructure", summary="i", confidence=0.5),
        "incident": AgentFinding(agent_name="incident", summary="a", confidence=0.7),
        "knowledge": AgentFinding(agent_name="knowledge", summary="k", confidence=0.4),
        "rca": AgentFinding(agent_name="rca", summary="r", confidence=0.9),
    }
    report = build_multi_agent_report(context, findings)
    assert report.investigation_id == "inv-1"
    assert report.rca_findings.summary == "r"
    assert "Lead signal from rca agent" in report.final_summary


@patch("agents.investigation_coordinator.load_agent_investigation_context")
def test_run_multi_agent_investigation_end_to_end(mock_load_context) -> None:
    mock_load_context.return_value = _sample_context()
    report = run_multi_agent_investigation(_MockClient(), "inv-1")
    assert report.investigation_id == "inv-1"
    assert report.timeline_findings.agent_name == "timeline"
    assert report.final_summary


@patch("agents.investigation_coordinator.load_agent_investigation_context", side_effect=KeyError("missing"))
def test_run_multi_agent_investigation_missing_raises(mock_load_context) -> None:
    with pytest.raises(KeyError):
        run_multi_agent_investigation(_MockClient(exists=False), "missing")
