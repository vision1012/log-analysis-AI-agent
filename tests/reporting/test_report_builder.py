"""Tests for investigation report builder."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.agent_models import AgentFinding, AgentInvestigationContext, MultiAgentInvestigationReport
from feedback.feedback_models import FeedbackRecord
from graph.retrieval_models import GraphArchitectureDocumentRecord, GraphRunbookRecord, SimilarInvestigation
from reporting.report_models import ArchitectureReferenceEntry
from investigation.timeline_models import InvestigationTimelineEvent
from reporting.report_builder import build_investigation_report


def _sample_context() -> AgentInvestigationContext:
    return AgentInvestigationContext(
        investigation_id="inv-report-1",
        ticket_key="OPS-42",
        service_name="auth-service",
        timeline_events=[
            InvestigationTimelineEvent(
                event_id="e1",
                timestamp="2024-01-01T09:00:00Z",
                event_type="ALERT_TRIGGERED",
                source="Datadog",
                title="High error rate",
            ),
            InvestigationTimelineEvent(
                event_id="e2",
                timestamp="2024-01-01T09:30:00Z",
                event_type="RCA_COMPLETED",
                source="RCA",
                title="RCA completed",
            ),
        ],
        runbooks=[
            GraphRunbookRecord(
                runbook_id="rb-1",
                title="Auth Recovery",
                service_name="auth-service",
                summary="Restart pods and verify login flow.",
                url="https://wiki.example/runbook",
            )
        ],
        architecture_documents=[
            GraphArchitectureDocumentRecord(
                document_id="arch-1",
                title="Auth Architecture",
                summary="Gateway and auth DB topology.",
                service="auth-service",
                subsystem="api-gateway",
                document_url="https://wiki.example/arch",
                relevance=0.95,
            )
        ],
        similar_investigations=[
            SimilarInvestigation(
                investigation_id="inv-old",
                similarity_score=0.82,
                root_cause="/srv/auth/handler.py",
                confidence=0.76,
                resolution_summary="Rolled back deployment",
                matched_factors=["service_match", "alert_match"],
            )
        ],
        feedback=[
            FeedbackRecord(
                feedback_id="fb-1",
                investigation_id="inv-report-1",
                candidate_id="/srv/auth/handler.py",
                feedback_type="CONFIRMED",
                comments="Matches logs",
                user_id="eng-1",
                created_at="2024-01-01T10:00:00Z",
            )
        ],
        store_record={
            "ticket_summary": "Authentication Failure",
            "ticket_key": "OPS-42",
            "relationship_ready_bundle": {"rca_target_file": "/srv/auth/handler.py"},
            "confidence_assessments": [
                {
                    "candidate": "/srv/auth/handler.py",
                    "confidence": 0.88,
                    "confidence_level": "high",
                    "supporting_factors": ["deployment_proximity"],
                    "contradicting_factors": [],
                    "coverage_score": 0.375,
                    "coverage_level": "partial",
                    "confidence_limitations": [
                        "Missing Jenkins",
                        "Missing PagerDuty",
                        "Missing Confluence",
                    ],
                }
            ],
            "derived_signals_snapshot": {
                "merged": {"error_keywords": ["timeout", "auth", "error"]},
            },
        },
    )


def _multi_agent_report() -> MultiAgentInvestigationReport:
    finding = AgentFinding(
        agent_name="deployment",
        summary="Recent deploy detected",
        suspicious_items=["Deploy within 15 minutes of alert"],
        confidence=0.7,
    )
    return MultiAgentInvestigationReport(
        investigation_id="inv-report-1",
        timeline_findings=AgentFinding(agent_name="timeline", summary="timeline ok"),
        deployment_findings=finding,
        infrastructure_findings=AgentFinding(agent_name="infrastructure", summary="infra ok"),
        incident_findings=AgentFinding(agent_name="incident", summary="incident ok"),
        knowledge_findings=AgentFinding(agent_name="knowledge", summary="knowledge ok"),
        rca_findings=AgentFinding(agent_name="rca", summary="rca ok", confidence=0.88),
        final_summary="Lead signal from rca agent (confidence 0.88): rca ok",
    )


@patch("reporting.report_builder.get_investigation_graph")
@patch("reporting.report_builder.run_agents")
@patch("reporting.report_builder.load_agent_investigation_context")
def test_build_investigation_report_assembles_fields(
    mock_load_context,
    mock_run_agents,
    mock_get_graph,
) -> None:
    context = _sample_context()
    mock_load_context.return_value = context
    mock_run_agents.return_value = {"rca": _multi_agent_report().rca_findings}
    mock_get_graph.return_value = {
        "nodes": [{"label": "Investigation"}, {"label": "AlertEvent"}],
        "edges": [{"type": "TRIGGERED"}],
    }

    client = MagicMock()
    report = build_investigation_report(client, "inv-report-1")

    assert report.investigation_id == "inv-report-1"
    assert report.title == "Authentication Failure"
    assert report.root_cause == "/srv/auth/handler.py"
    assert report.confidence == pytest.approx(0.88)
    assert "Confidence for /srv/auth/handler.py" in report.confidence_reasoning
    assert "Timeline spans" in report.timeline_summary
    assert "2 nodes" in report.graph_summary
    assert len(report.similar_incidents) == 1
    assert report.similar_incidents[0].investigation_id == "inv-old"
    assert len(report.feedback_history) == 1
    assert report.feedback_history[0].feedback_type == "CONFIRMED"
    assert len(report.runbooks) == 1
    assert report.runbooks[0].title == "Auth Recovery"
    assert len(report.architecture_references) == 1
    assert report.architecture_references[0].title == "Auth Architecture"
    assert report.architecture_references[0].subsystem == "api-gateway"
    assert report.remediation_steps
    assert report.multi_agent_summary
    assert report.evidence_coverage.coverage_score == pytest.approx(0.375)
    assert report.evidence_coverage.coverage_level == "partial"
    assert "jenkins" in report.evidence_coverage.missing_sources
    assert "Missing Jenkins" in report.evidence_coverage.confidence_limitations
    assert report.keyword_evidence.matched_keywords
    assert report.keyword_evidence.keyword_score > 0
    assert report.generated_at


@patch("reporting.report_builder._get_evidence_store")
def test_resolve_confidence_from_evidence_bundle(mock_get_store) -> None:
    from reporting.report_builder import _resolve_confidence, _resolve_evidence_coverage

    mock_get_store.return_value.get_bundle.return_value = {
        "confidence_assessment": {
            "candidate": "/app/main.py",
            "confidence": 0.65,
            "confidence_level": "medium",
            "supporting_factors": ["alert_correlation"],
            "contradicting_factors": [],
            "coverage_score": 0.25,
            "coverage_level": "partial",
            "confidence_limitations": ["Missing Datadog"],
        },
        "keyword_signal": {
            "matched_keywords": ["timeout", "error"],
            "keyword_score": 0.7,
            "keyword_categories": ["Performance"],
        },
        "attributed_file_id": "/app/main.py",
    }
    store_record = {
        "rca_result_ref": {"evidence_refs": ["bundle-1"]},
    }
    confidence, reasoning = _resolve_confidence(store_record)
    assert confidence == pytest.approx(0.65)
    assert "Confidence for /app/main.py" in reasoning

    coverage = _resolve_evidence_coverage(store_record)
    assert coverage.coverage_score == pytest.approx(0.25)
    assert coverage.coverage_level == "partial"
    assert coverage.confidence_limitations == ["Missing Datadog"]
    assert coverage.missing_sources == ["datadog"]

    from reporting.report_builder import _resolve_keyword_evidence

    keyword = _resolve_keyword_evidence(store_record, "/app/main.py")
    assert keyword.keyword_score == pytest.approx(0.7)
    assert "timeout" in keyword.matched_keywords
