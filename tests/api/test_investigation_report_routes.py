"""API route tests for investigation report export."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.services.investigation_graph_service import InvestigationGraphNotFoundError
from reporting.report_models import InvestigationReport


def _report() -> InvestigationReport:
    return InvestigationReport(
        investigation_id="inv-1",
        title="Auth Failure",
        executive_summary="Auth service failure after deploy.",
        timeline_summary="Timeline with 3 events.",
        graph_summary="Graph with 5 nodes.",
        root_cause="/srv/auth/handler.py",
        confidence=0.85,
        confidence_reasoning="Confidence is high.",
        multi_agent_summary="Lead signal from rca agent.",
        generated_at="2024-01-01T12:00:00Z",
    )


def test_investigation_report_endpoint_success() -> None:
    from api.routes.investigation_graph import get_investigation_report_endpoint

    with patch(
        "api.routes.investigation_graph.fetch_investigation_report",
        return_value=_report(),
    ):
        body = asyncio.run(get_investigation_report_endpoint("inv-1"))

    assert body["report"]["investigation_id"] == "inv-1"
    assert body["report"]["root_cause"] == "/srv/auth/handler.py"


def test_investigation_report_endpoint_not_found() -> None:
    from api.routes.investigation_graph import get_investigation_report_endpoint

    with patch(
        "api.routes.investigation_graph.fetch_investigation_report",
        side_effect=InvestigationGraphNotFoundError("missing"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_investigation_report_endpoint("missing"))

    assert exc.value.status_code == 404


def test_investigation_report_pdf_endpoint_success(tmp_path) -> None:
    from api.routes.investigation_graph import get_investigation_report_pdf_endpoint

    pdf_path = tmp_path / "inv-1.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    with patch(
        "api.routes.investigation_graph.fetch_investigation_report_pdf",
        return_value=(pdf_path, _report()),
    ):
        response = asyncio.run(get_investigation_report_pdf_endpoint("inv-1"))

    assert response.media_type == "application/pdf"
    assert response.filename == "inv-1.pdf"
    assert isinstance(response.path, (str, Path))


def test_investigation_report_markdown_endpoint_success(tmp_path) -> None:
    from api.routes.investigation_graph import get_investigation_report_markdown_endpoint

    md_path = tmp_path / "inv-1.md"
    md_path.write_text("# Report", encoding="utf-8")

    with patch(
        "api.routes.investigation_graph.fetch_investigation_report_markdown",
        return_value=(md_path, _report()),
    ):
        response = asyncio.run(get_investigation_report_markdown_endpoint("inv-1"))

    assert response.media_type == "text/markdown"
    assert response.filename == "inv-1.md"
