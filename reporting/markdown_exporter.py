"""Markdown export for investigation reports."""

from __future__ import annotations

from pathlib import Path

from reporting.report_builder import get_reports_dir
from reporting.report_models import EvidenceCoverageSection, InvestigationReport, KeywordEvidenceSection


def _section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip()}\n\n"


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "_None recorded._"
    return "\n".join(f"- {item}" for item in items)


def _format_evidence_coverage(section: EvidenceCoverageSection) -> str:
    available = _bullet_list(section.available_sources) if section.available_sources else "_None recorded._"
    missing = _bullet_list(section.missing_sources) if section.missing_sources else "_None recorded._"
    limitations = (
        _bullet_list(section.confidence_limitations)
        if section.confidence_limitations
        else "_None recorded._"
    )
    return (
        f"**Coverage Score:** {section.coverage_score:.2f}\n\n"
        f"**Coverage Level:** {section.coverage_level}\n\n"
        f"**Available Sources:**\n{available}\n\n"
        f"**Missing Sources:**\n{missing}\n\n"
        f"**Confidence Limitations:**\n{limitations}"
    )


def _format_keyword_evidence(section: KeywordEvidenceSection) -> str:
    keywords = _bullet_list(section.matched_keywords) if section.matched_keywords else "_None matched._"
    categories = _bullet_list(section.keyword_categories) if section.keyword_categories else "_None classified._"
    path = section.candidate_path or "Not determined"
    return (
        f"**Candidate Path:** {path}\n\n"
        f"**Keyword Score:** {section.keyword_score:.2f}\n\n"
        f"**Matched Keywords:**\n{keywords}\n\n"
        f"**Keyword Categories:**\n{categories}"
    )


def render_markdown(report: InvestigationReport) -> str:
    """Render an investigation report as Markdown."""
    lines = [
        f"# Investigation Report: {report.title}",
        "",
        f"**Investigation ID:** {report.investigation_id}  ",
        f"**Generated:** {report.generated_at}",
        "",
        _section("Executive Summary", report.executive_summary),
        _section("Timeline", report.timeline_summary),
        _section(
            "RCA Findings",
            f"**Root cause:** {report.root_cause or 'Not determined'}\n\n"
            f"**Confidence:** {report.confidence:.2f}",
        ),
        _section(
            "Confidence Assessment",
            report.confidence_reasoning or "No confidence reasoning available.",
        ),
        _section("Evidence Coverage", _format_evidence_coverage(report.evidence_coverage)),
        _section("Keyword Evidence", _format_keyword_evidence(report.keyword_evidence)),
    ]

    similar_lines = []
    for item in report.similar_incidents:
        similar_lines.append(
            f"- **{item.investigation_id}** (score {item.similarity_score:.2f}): "
            f"{item.root_cause or 'unknown root cause'} — {item.resolution_summary or 'no resolution summary'}"
        )
    lines.append(_section("Similar Incidents", "\n".join(similar_lines) if similar_lines else "_None found._"))

    lines.append(_section("Multi-Agent Findings", report.multi_agent_summary or "_No multi-agent summary._"))

    runbook_lines = []
    for runbook in report.runbooks:
        detail = runbook.summary or "See linked runbook."
        url = f" ({runbook.url})" if runbook.url else ""
        runbook_lines.append(f"- **{runbook.title}** [{runbook.service_name}]{url}: {detail}")
    lines.append(_section("Runbooks", "\n".join(runbook_lines) if runbook_lines else "_None matched._"))

    architecture_lines = []
    for arch in report.architecture_references:
        url = f" ({arch.document_url})" if arch.document_url else ""
        subsystem = f" / {arch.subsystem}" if arch.subsystem else ""
        detail = arch.summary or "See linked architecture document."
        architecture_lines.append(
            f"- **{arch.title}** [{arch.service}{subsystem}] (relevance {arch.relevance:.2f}){url}: {detail}"
        )
    lines.append(
        _section(
            "Architecture References",
            "\n".join(architecture_lines) if architecture_lines else "_None matched._",
        )
    )

    lines.append(_section("Recommended Actions", _bullet_list(report.remediation_steps)))

    if report.feedback_history:
        feedback_lines = []
        for entry in report.feedback_history:
            feedback_lines.append(
                f"- {entry.created_at}: {entry.feedback_type} on {entry.candidate_id}"
                + (f" — {entry.comments}" if entry.comments else "")
            )
        lines.append(_section("Feedback History", "\n".join(feedback_lines)))

    return "\n".join(lines).strip() + "\n"


def export_markdown(report: InvestigationReport, *, reports_dir: Path | None = None) -> Path:
    """Write Markdown report to artifacts/reports/ and return the file path."""
    target_dir = reports_dir or get_reports_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{report.investigation_id}.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return path
