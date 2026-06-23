"""Tests for Markdown investigation report export."""

from __future__ import annotations

from reporting.markdown_exporter import export_markdown, render_markdown
from reporting.report_models import (
    EvidenceCoverageSection,
    InvestigationReport,
    RunbookEntry,
    SimilarIncidentEntry,
)


def _sample_report() -> InvestigationReport:
    return InvestigationReport(
        investigation_id="inv-md-1",
        title="Payment Failure",
        executive_summary="Payment service degraded after deploy.",
        timeline_summary="Timeline spans 09:00 to 10:00 with 5 events.",
        graph_summary="Investigation graph contains 8 nodes and 12 relationships.",
        root_cause="/srv/payment/processor.py",
        confidence=0.91,
        confidence_reasoning="Confidence for /srv/payment/processor.py is 0.91 (high).",
        similar_incidents=[
            SimilarIncidentEntry(
                investigation_id="inv-prev",
                similarity_score=0.77,
                root_cause="/srv/payment/processor.py",
                resolution_summary="Rollback fixed issue",
            )
        ],
        runbooks=[
            RunbookEntry(
                title="Payment Rollback",
                service_name="payment-service",
                summary="Rollback to previous deployment.",
            )
        ],
        remediation_steps=["Follow runbook 'Payment Rollback': Rollback to previous deployment."],
        multi_agent_summary="Lead signal from deployment agent.",
        evidence_coverage=EvidenceCoverageSection(
            coverage_score=0.375,
            coverage_level="partial",
            available_sources=["jira", "github", "datadog"],
            missing_sources=["jenkins", "pagerduty", "confluence"],
            confidence_limitations=["Missing Jenkins", "Missing PagerDuty", "Missing Confluence"],
        ),
        generated_at="2024-01-01T12:00:00Z",
    )


def test_render_markdown_includes_all_sections() -> None:
    content = render_markdown(_sample_report())
    assert "# Investigation Report: Payment Failure" in content
    assert "## Executive Summary" in content
    assert "## Timeline" in content
    assert "## RCA Findings" in content
    assert "## Confidence Assessment" in content
    assert "## Evidence Coverage" in content
    assert "**Coverage Score:** 0.38" in content
    assert "**Coverage Level:** partial" in content
    assert "Missing Jenkins" in content
    assert "## Similar Incidents" in content
    assert "## Multi-Agent Findings" in content
    assert "## Runbooks" in content
    assert "## Recommended Actions" in content
    assert "/srv/payment/processor.py" in content


def test_export_markdown_writes_file(tmp_path) -> None:
    report = _sample_report()
    path = export_markdown(report, reports_dir=tmp_path)
    assert path.exists()
    assert path.name == "inv-md-1.md"
    assert "Payment Failure" in path.read_text(encoding="utf-8")
