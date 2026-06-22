"""PDF export for investigation reports."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from reporting.report_builder import get_reports_dir
from reporting.report_models import InvestigationReport


def _safe_text(value: str) -> str:
    """Replace characters that core PDF fonts cannot render."""
    return (
        value.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .encode("latin-1", errors="replace")
        .decode("latin-1")
    )


class _InvestigationPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 12)
        self.cell(
            0,
            8,
            _safe_text("Investigation Report"),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")


def _write_section(pdf: _InvestigationPDF, title: str, body: str) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(pdf.epw, 6, _safe_text(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(pdf.epw, 5, _safe_text(body), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)


def _write_bullets(pdf: _InvestigationPDF, title: str, items: list[str]) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(pdf.epw, 6, _safe_text(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    if not items:
        pdf.multi_cell(pdf.epw, 5, _safe_text("None recorded."), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        for item in items:
            pdf.multi_cell(pdf.epw, 5, _safe_text(f"- {item}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)


def render_pdf_bytes(report: InvestigationReport) -> bytes:
    """Render an investigation report as PDF bytes."""
    pdf = _InvestigationPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(pdf.epw, 7, _safe_text(report.title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        pdf.epw,
        5,
        _safe_text(f"Investigation ID: {report.investigation_id}"),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.multi_cell(
        pdf.epw,
        5,
        _safe_text(f"Generated: {report.generated_at}"),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(4)

    _write_section(pdf, "1. Executive Summary", report.executive_summary)
    _write_section(pdf, "2. Timeline", report.timeline_summary)
    _write_section(
        pdf,
        "3. RCA Findings",
        f"Root cause: {report.root_cause or 'Not determined'}\nConfidence: {report.confidence:.2f}",
    )
    _write_section(
        pdf,
        "4. Confidence Assessment",
        report.confidence_reasoning or "No confidence reasoning available.",
    )

    similar_lines = []
    for item in report.similar_incidents:
        similar_lines.append(
            f"{item.investigation_id} (score {item.similarity_score:.2f}): "
            f"{item.root_cause or 'unknown'} — {item.resolution_summary or 'no resolution'}"
        )
    _write_bullets(pdf, "5. Similar Incidents", similar_lines)

    _write_section(pdf, "6. Multi-Agent Findings", report.multi_agent_summary or "No multi-agent summary.")

    runbook_lines = []
    for runbook in report.runbooks:
        detail = runbook.summary or "See linked runbook."
        runbook_lines.append(f"{runbook.title} [{runbook.service_name}]: {detail}")
    _write_bullets(pdf, "7. Runbooks", runbook_lines)

    _write_bullets(pdf, "8. Recommended Actions", report.remediation_steps)

    out = pdf.output()
    if isinstance(out, bytearray):
        return bytes(out)
    if isinstance(out, bytes):
        return out
    return out.encode("latin-1")


def export_pdf(report: InvestigationReport, *, reports_dir: Path | None = None) -> Path:
    """Write PDF report to artifacts/reports/ and return the file path."""
    target_dir = reports_dir or get_reports_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{report.investigation_id}.pdf"
    path.write_bytes(render_pdf_bytes(report))
    return path
