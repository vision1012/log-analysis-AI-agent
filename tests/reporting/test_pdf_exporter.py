"""Tests for PDF investigation report export."""

from __future__ import annotations

from reporting.pdf_exporter import export_pdf, render_pdf_bytes
from reporting.report_models import EvidenceCoverageSection, InvestigationReport


def _sample_report() -> InvestigationReport:
    return InvestigationReport(
        investigation_id="inv-pdf-1",
        title="API Latency Regression",
        executive_summary="Latency increased after deploy on api-gateway.",
        timeline_summary="Timeline spans 08:00 to 09:00 with 4 events.",
        graph_summary="Investigation graph contains 6 nodes and 9 relationships.",
        root_cause="/srv/api/router.py",
        confidence=0.73,
        confidence_reasoning="Confidence for /srv/api/router.py is 0.73 (medium).",
        remediation_steps=["Review recent deployment changes."],
        multi_agent_summary="Lead signal from timeline agent.",
        evidence_coverage=EvidenceCoverageSection(
            coverage_score=0.5,
            coverage_level="good",
            available_sources=["jira", "datadog"],
            missing_sources=["jenkins"],
            confidence_limitations=["Missing Jenkins"],
        ),
        generated_at="2024-01-01T12:00:00Z",
    )


def test_render_pdf_bytes_produces_pdf_header() -> None:
    data = render_pdf_bytes(_sample_report())
    assert data.startswith(b"%PDF")
    assert len(data) > 500


def test_export_pdf_writes_file(tmp_path) -> None:
    report = _sample_report()
    path = export_pdf(report, reports_dir=tmp_path)
    assert path.exists()
    assert path.name == "inv-pdf-1.pdf"
    assert path.read_bytes().startswith(b"%PDF")
