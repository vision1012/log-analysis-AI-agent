"""Markdown export for investigation reports."""

from __future__ import annotations

from pathlib import Path

from reporting.report_builder import get_reports_dir
from reporting.report_models import InvestigationReport


def _section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip()}\n\n"


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "_None recorded._"
    return "\n".join(f"- {item}" for item in items)


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
