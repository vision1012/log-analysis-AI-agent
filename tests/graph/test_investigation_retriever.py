"""Tests for InvestigationGraphRetriever read APIs."""

from __future__ import annotations

from typing import Any

import pytest

from graph.investigation_retriever import InvestigationGraphRetriever
from graph.retrieval_models import (
    GraphAlertRecord,
    GraphCommitRecord,
    GraphDeploymentRecord,
    GraphIncidentRecord,
    GraphInvestigationRecord,
    GraphKnownIssueRecord,
    GraphRunbookRecord,
)


class _MockReadClient:
    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        self._responses = responses
        self.queries: list[tuple[str, dict[str, Any] | None]] = []

    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.queries.append((query, parameters))
        key = _query_key(query)
        return list(self._responses.get(key, []))


def _query_key(query: str) -> str:
    normalized = " ".join(query.split())
    if "similarity_score" in normalized:
        return "similar_investigations"
    if "MATCHES_KNOWN_ISSUE" in normalized:
        return "known_issues"
    if "TRIGGERED_BUILD" in normalized:
        return "commits_primary"
    if "Commit {sha: d.commit_sha}" in normalized:
        return "commits_fallback"
    if "ESCALATED_TO" in normalized and "Investigation {id:" not in normalized:
        return "incidents_by_alert_service"
    if "AlertEvent" in normalized and "Investigation {id:" in normalized and "PagerDutyIncident" not in normalized:
        return "alerts_by_investigation"
    if "MATCH (a:AlertEvent)" in normalized and "Investigation" not in normalized:
        return "alerts_by_service"
    if "PagerDutyIncident" in normalized and "Investigation {id:" in normalized:
        return "incidents_by_investigation"
    if "Investigation {id:" in normalized and "Deployment" in normalized:
        return "deployments_by_investigation"
    if "HAS_RUNBOOK" in normalized and "Service {name:" in normalized:
        return "runbooks_service_link"
    if "MATCH (r:Runbook)" in normalized:
        return "runbooks_direct"
    if "MetricEvent" in normalized and "Deployment)-[:OBSERVED_METRIC]" in normalized.replace(" ", ""):
        return "deployments_by_service"
    if "MATCH (d:Deployment)" in normalized and "ORDER BY d.deployed_at" in normalized:
        return "deployments_all"
    return "unknown"


@pytest.fixture
def mock_client() -> _MockReadClient:
    return _MockReadClient(
        {
            "deployments_by_investigation": [
                {
                    "deployment_id": "dep-1",
                    "environment": "prod",
                    "status": "SUCCESS",
                    "commit_sha": "abc123",
                    "deployed_at": "2024-01-01T11:00:00Z",
                    "deployment_url": "https://deploy/1",
                    "service_name": "auth-service",
                    "investigation_id": "inv-1",
                }
            ],
            "incidents_by_alert_service": [
                {
                    "incident_id": "INC123",
                    "incident_number": 4567,
                    "title": "High error rate",
                    "service_name": "auth-service",
                    "urgency": "high",
                    "status": "triggered",
                    "created_at": "2024-01-01T12:10:00Z",
                    "resolved_at": None,
                    "html_url": "https://pd/Inc123",
                    "alert_id": "alert-1",
                    "investigation_id": "",
                }
            ],
            "commits_primary": [
                {
                    "sha": "abc123",
                    "message": "Fix timeout",
                    "author": "dev@example.com",
                    "committed_at": "2024-01-01T10:00:00Z",
                    "repo_ref": "org/repo",
                    "service_name": "auth-service",
                }
            ],
            "known_issues": [
                {
                    "known_issue_id": "KI1",
                    "title": "Known OOM",
                    "affected_service": "auth-service",
                    "workaround": "Increase memory",
                    "severity": "high",
                    "url": "https://wiki/KI1",
                    "alert_id": "alert-1",
                }
            ],
            "runbooks_service_link": [
                {
                    "runbook_id": "RB1",
                    "title": "auth-service Runbook",
                    "service_name": "auth-service",
                    "summary": "Rollback steps",
                    "url": "https://wiki/RB1",
                    "space_key": "OPS",
                    "updated_at": "2024-01-01T09:00:00Z",
                }
            ],
            "similar_investigations": [
                {
                    "investigation_id": "inv-old",
                    "ticket_key": "OPS-10",
                    "created_at": "2024-01-01T08:00:00Z",
                    "updated_at": None,
                    "similarity_score": 0.7,
                    "shared_service": "auth-service",
                    "match_reason": "same_project",
                }
            ],
        }
    )


def test_get_related_deployments_by_investigation(mock_client: _MockReadClient) -> None:
    retriever = InvestigationGraphRetriever(mock_client)
    results = retriever.get_related_deployments(investigation_id="inv-1")
    assert len(results) == 1
    assert isinstance(results[0], GraphDeploymentRecord)
    assert results[0].deployment_id == "dep-1"
    assert results[0].service_name == "auth-service"


def test_get_related_incidents_by_service(mock_client: _MockReadClient) -> None:
    retriever = InvestigationGraphRetriever(mock_client)
    results = retriever.get_related_incidents(service_name="auth-service")
    assert len(results) == 1
    assert isinstance(results[0], GraphIncidentRecord)
    assert results[0].incident_id == "INC123"
    assert results[0].alert_id == "alert-1"


def test_get_related_alerts_by_service(mock_client: _MockReadClient) -> None:
    client = _MockReadClient(
        {
            "alerts_by_service": [
                {
                    "alert_id": "alert-1",
                    "title": "High error rate",
                    "message": "error spike",
                    "severity": "critical",
                    "service": "auth-service",
                    "status": "triggered",
                    "triggered_at": "2024-01-01T12:05:00Z",
                    "resolved_at": None,
                    "investigation_id": "",
                }
            ]
        }
    )
    retriever = InvestigationGraphRetriever(client)
    results = retriever.get_related_alerts(service_name="auth-service")
    assert len(results) == 1
    assert isinstance(results[0], GraphAlertRecord)
    assert results[0].alert_id == "alert-1"


def test_get_recent_commits_for_service(mock_client: _MockReadClient) -> None:
    retriever = InvestigationGraphRetriever(mock_client)
    results = retriever.get_recent_commits_for_service("auth-service")
    assert len(results) == 1
    assert isinstance(results[0], GraphCommitRecord)
    assert results[0].sha == "abc123"


def test_get_known_issues_for_alert(mock_client: _MockReadClient) -> None:
    retriever = InvestigationGraphRetriever(mock_client)
    results = retriever.get_known_issues_for_alert("alert-1")
    assert len(results) == 1
    assert isinstance(results[0], GraphKnownIssueRecord)
    assert results[0].known_issue_id == "KI1"


def test_get_runbooks_for_service(mock_client: _MockReadClient) -> None:
    retriever = InvestigationGraphRetriever(mock_client)
    results = retriever.get_runbooks_for_service("auth-service")
    assert len(results) == 1
    assert isinstance(results[0], GraphRunbookRecord)
    assert results[0].runbook_id == "RB1"


def test_get_previous_similar_investigations(mock_client: _MockReadClient) -> None:
    retriever = InvestigationGraphRetriever(mock_client)
    results = retriever.get_previous_similar_investigations(
        investigation_id="inv-1",
        service_name="auth-service",
        ticket_key="OPS-20",
    )
    assert len(results) == 1
    assert isinstance(results[0], GraphInvestigationRecord)
    assert results[0].investigation_id == "inv-old"
    assert results[0].match_reason == "same_project"
