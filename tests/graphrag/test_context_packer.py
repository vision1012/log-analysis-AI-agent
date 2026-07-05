"""Tests for GraphRAG context packer investigation retrieval expansion."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from graph.retrieval_models import (
    GraphAlertRecord,
    GraphArchitectureDocumentRecord,
    GraphCommitRecord,
    GraphDeploymentRecord,
    GraphIncidentRecord,
    GraphInvestigationRecord,
    GraphKnownIssueRecord,
    GraphRunbookRecord,
)
from graphrag.context_packer import pack_context


class _MockGraphClient:
    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "MATCH (a:Anomaly {id:" in query and "RCA_ATTRIBUTED" not in query:
            return [{"anomaly_id": "an-1", "trace_ref": "trace-1", "service_ref": "auth-service"}]
        if "RCA_ATTRIBUTED" in query and "LIMIT 1" in query:
            return [{"run_id": "run-1", "ts": "2024-01-01T12:00:00Z"}]
        if "RCA_ATTRIBUTED" in query:
            return [
                {
                    "run_id": "run-1",
                    "status": "candidate",
                    "confidence": 0.8,
                    "evidence_ref": "bundle-1",
                    "file_id": "file-1",
                    "path": "/srv/auth/handler.py",
                }
            ]
        return []


class _MockEvidenceStore:
    def get_bundle(self, evidence_ref: str) -> dict[str, Any] | None:
        return {
            "signal_scores": {"last_touch_recency": 0.5, "historical_recurrence": 0.2},
            "weights_used": {},
            "raw_score": 0.8,
            "capped_score": 0.8,
            "path": "/srv/auth/handler.py",
            "last_touch_commit_sha": "abc123",
            "deployment_id": "dep-1",
            "prior_count": 1,
        }


@patch("graphrag.context_packer.InvestigationGraphRetriever")
def test_pack_context_includes_investigation_retrieval(mock_retriever_cls) -> None:
    retriever = MagicMock()
    mock_retriever_cls.return_value = retriever
    retriever.get_related_deployments.return_value = [
        GraphDeploymentRecord(
            deployment_id="dep-1",
            environment="prod",
            status="SUCCESS",
            commit_sha="abc123",
            service_name="auth-service",
        )
    ]
    retriever.get_related_alerts.return_value = [
        GraphAlertRecord(alert_id="alert-1", title="High error rate", service="auth-service")
    ]
    retriever.get_related_incidents.return_value = [
        GraphIncidentRecord(incident_id="INC1", title="Incident", service_name="auth-service")
    ]
    retriever.get_recent_commits_for_service.return_value = [
        GraphCommitRecord(sha="abc123", message="Fix timeout", service_name="auth-service")
    ]
    retriever.get_runbooks_for_service.return_value = [
        GraphRunbookRecord(runbook_id="RB1", title="Runbook", service_name="auth-service")
    ]
    retriever.get_architecture_documents.return_value = [
        GraphArchitectureDocumentRecord(
            document_id="arch-1",
            title="Auth Architecture",
            summary="Topology overview",
            service="auth-service",
            subsystem="api-gateway",
            document_url="https://wiki/arch-1",
            relevance=1.0,
        )
    ]
    retriever.get_known_issues_for_alert.return_value = [
        GraphKnownIssueRecord(known_issue_id="KI1", title="Known OOM", affected_service="auth-service")
    ]
    retriever.get_previous_similar_investigations.return_value = [
        GraphInvestigationRecord(investigation_id="inv-old", ticket_key="OPS-10", match_reason="same_project")
    ]

    client = _MockGraphClient()
    client._driver = object()
    pack = pack_context(
        "an-1",
        graph_client=client,  # type: ignore[arg-type]
        evidence_store=_MockEvidenceStore(),
        investigation_id="inv-1",
        service_name="auth-service",
        ticket_key="OPS-20",
    )

    ctx = pack["investigation_context"]
    assert len(ctx["related_deployments"]) == 1
    assert ctx["related_deployments"][0]["deployment_id"] == "dep-1"
    assert len(ctx["related_alerts"]) == 1
    assert len(ctx["related_incidents"]) == 1
    assert len(ctx["related_commits"]) == 1
    assert len(ctx["runbooks"]) == 1
    assert len(ctx["architecture_documents"]) == 1
    assert ctx["architecture_documents"][0]["title"] == "Auth Architecture"
    assert len(ctx["known_issues"]) == 1
    assert len(ctx["previous_investigations"]) == 1
    assert pack["candidates"]


@patch("graphrag.context_packer.InvestigationGraphRetriever", side_effect=RuntimeError("neo4j down"))
def test_pack_context_survives_investigation_retrieval_failure(mock_retriever_cls) -> None:
    client = _MockGraphClient()
    client._driver = object()
    pack = pack_context(
        "an-1",
        graph_client=client,  # type: ignore[arg-type]
        evidence_store=_MockEvidenceStore(),
        investigation_id="inv-1",
        service_name="auth-service",
    )
    ctx = pack["investigation_context"]
    assert ctx["related_deployments"] == []
    assert ctx["related_alerts"] == []
    assert pack["candidates"]
