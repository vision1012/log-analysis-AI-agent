"""API layer for investigation report export."""

from __future__ import annotations

from pathlib import Path

from api.services.investigation_graph_service import InvestigationGraphNotFoundError
from graph.neo4j_client import Neo4jClient
from reporting.markdown_exporter import export_markdown
from reporting.pdf_exporter import export_pdf
from reporting.report_builder import build_investigation_report
from reporting.report_models import InvestigationReport


def _get_client() -> Neo4jClient:
    return Neo4jClient.from_env()


def fetch_investigation_report(investigation_id: str) -> InvestigationReport:
    """Build and return a unified investigation report."""
    client = _get_client()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        return build_investigation_report(client, investigation_id)
    except KeyError as exc:
        raise InvestigationGraphNotFoundError(str(exc)) from exc
    finally:
        if getattr(client, "_driver", None):
            client.close()


def fetch_investigation_report_pdf(investigation_id: str) -> tuple[Path, InvestigationReport]:
    """Build report, export PDF to artifacts/reports/, and return path + report."""
    report = fetch_investigation_report(investigation_id)
    path = export_pdf(report)
    return path, report


def fetch_investigation_report_markdown(investigation_id: str) -> tuple[Path, InvestigationReport]:
    """Build report, export Markdown to artifacts/reports/, and return path + report."""
    report = fetch_investigation_report(investigation_id)
    path = export_markdown(report)
    return path, report
