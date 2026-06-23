"""Assemble unified investigation reports from existing data sources."""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.agent_models import MultiAgentInvestigationReport
from agents.investigation_context_loader import load_agent_investigation_context
from agents.investigation_coordinator import build_multi_agent_report, run_agents
from feedback.feedback_models import FeedbackRecord
from graph.graph_visualization_service import get_investigation_graph
from graph.neo4j_client import Neo4jClient
from graph.retrieval_models import GraphRunbookRecord, SimilarInvestigation
from investigation.timeline_models import InvestigationTimelineEvent
from rca_engine.confidence_engine import build_confidence_reasoning
from reporting.report_models import (
    EvidenceCoverageSection,
    FeedbackHistoryEntry,
    InvestigationReport,
    RunbookEntry,
    SimilarIncidentEntry,
)


def get_reports_dir() -> Path:
    """Return the directory where generated reports are stored."""
    configured = (os.environ.get("INVESTIGATION_REPORTS_DIR") or "").strip()
    if configured:
        path = Path(configured)
    else:
        path = Path(__file__).resolve().parent.parent / "artifacts" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_investigation_store():
    from artifacts.investigation_store import LocalFileInvestigationStore

    base = os.environ.get("JIRA_INVESTIGATION_STORE_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        "jira_rca_investigations",
    )
    return LocalFileInvestigationStore(base)


def _get_evidence_store():
    from artifacts.evidence_store import LocalFileEvidenceStore

    base = os.environ.get("EVIDENCE_STORE_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        "evidence_bundles",
    )
    return LocalFileEvidenceStore(base)


_PROVIDER_LABELS: dict[str, str] = {
    "jira": "Jira",
    "github": "GitHub",
    "gitlab": "GitLab",
    "jenkins": "Jenkins",
    "datadog": "Datadog",
    "kubernetes": "Kubernetes",
    "pagerduty": "PagerDuty",
    "confluence": "Confluence",
}


def _top_confidence_assessment(store_record: dict[str, Any]) -> dict[str, Any]:
    assessments = store_record.get("confidence_assessments") or []
    if isinstance(assessments, list):
        for item in assessments:
            if isinstance(item, dict):
                return item

    refs = (store_record.get("rca_result_ref") or {}).get("evidence_refs") or []
    if isinstance(refs, list):
        evidence_store = _get_evidence_store()
        for ref in refs:
            if not isinstance(ref, str):
                continue
            bundle = evidence_store.get_bundle(ref)
            if not isinstance(bundle, dict):
                continue
            assessment = bundle.get("confidence_assessment")
            if isinstance(assessment, dict):
                return assessment
    return {}


def _missing_sources_from_limitations(limitations: list[Any]) -> list[str]:
    label_to_source = {label.lower(): key for key, label in _PROVIDER_LABELS.items()}
    missing: list[str] = []
    for item in limitations:
        text = str(item or "").strip()
        if not text.lower().startswith("missing "):
            continue
        label = text[len("Missing ") :].strip().lower()
        source = label_to_source.get(label)
        if source:
            missing.append(source)
    return missing


def _limitations_from_missing_sources(missing_sources: list[Any]) -> list[str]:
    limitations: list[str] = []
    for source in missing_sources:
        key = str(source or "").strip().lower()
        if not key:
            continue
        label = _PROVIDER_LABELS.get(key, key.replace("_", " ").title())
        limitations.append(f"Missing {label}")
    return limitations


def _resolve_evidence_coverage(store_record: dict[str, Any]) -> EvidenceCoverageSection:
    raw = store_record.get("evidence_coverage")
    if isinstance(raw, dict):
        missing = list(raw.get("missing_sources") or [])
        limitations = list(raw.get("confidence_limitations") or [])
        if not limitations and missing:
            limitations = _limitations_from_missing_sources(missing)
        return EvidenceCoverageSection(
            coverage_score=float(raw.get("coverage_score") or 0.0),
            coverage_level=str(raw.get("coverage_level") or "low"),
            available_sources=[str(s) for s in (raw.get("available_sources") or []) if s],
            missing_sources=[str(s) for s in missing if s],
            confidence_limitations=[str(item) for item in limitations if item],
        )

    assessment = _top_confidence_assessment(store_record)
    if assessment:
        missing = [str(s) for s in (assessment.get("missing_sources") or []) if s]
        limitations = [str(item) for item in (assessment.get("confidence_limitations") or []) if item]
        if not missing and limitations:
            missing = _missing_sources_from_limitations(limitations)
        available = [str(s) for s in (assessment.get("available_sources") or []) if s]
        if not limitations and missing:
            limitations = _limitations_from_missing_sources(missing)
        return EvidenceCoverageSection(
            coverage_score=float(assessment.get("coverage_score") or 0.0),
            coverage_level=str(assessment.get("coverage_level") or "low"),
            available_sources=available,
            missing_sources=missing,
            confidence_limitations=limitations,
        )

    return EvidenceCoverageSection()


def _resolve_confidence(store_record: dict[str, Any]) -> tuple[float, str]:
    assessment = _top_confidence_assessment(store_record)
    if assessment:
        confidence = float(assessment.get("confidence") or 0.0)
        return confidence, build_confidence_reasoning(assessment)

    return 0.0, "No confidence assessment available."


def _resolve_root_cause(store_record: dict[str, Any]) -> str:
    bundle = store_record.get("relationship_ready_bundle") or {}
    if isinstance(bundle, dict):
        target = bundle.get("rca_target_file")
        if target:
            return str(target)
        paths = bundle.get("candidate_file_paths") or []
        if isinstance(paths, list) and paths:
            return str(paths[0])
    merged = (store_record.get("derived_signals_snapshot") or {}).get("merged") or {}
    file_paths = merged.get("file_paths") or []
    if isinstance(file_paths, list) and file_paths:
        return str(file_paths[0])
    return ""


def _resolve_title(store_record: dict[str, Any], investigation_id: str) -> str:
    for key in ("ticket_summary", "ticket_key"):
        value = store_record.get(key)
        if value:
            return str(value)
    return investigation_id


def _build_timeline_summary(events: list[InvestigationTimelineEvent]) -> str:
    if not events:
        return "No timeline events recorded for this investigation."

    sorted_events = sorted(events, key=lambda event: event.timestamp)
    first = sorted_events[0]
    last = sorted_events[-1]
    type_counts = Counter(event.event_type for event in sorted_events)
    top_types = ", ".join(f"{name} ({count})" for name, count in type_counts.most_common(5))
    highlights = []
    for event in sorted_events[:3]:
        highlights.append(f"{event.timestamp}: {event.title} ({event.event_type})")

    parts = [
        f"Timeline spans {first.timestamp} to {last.timestamp} with {len(sorted_events)} events.",
        f"Event types: {top_types}.",
    ]
    if highlights:
        parts.append("Early events: " + "; ".join(highlights) + ".")
    return " ".join(parts)


def _build_graph_summary(client: Neo4jClient, investigation_id: str) -> str:
    graph = get_investigation_graph(client, investigation_id, depth=2)
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        return "No investigation graph nodes found."

    label_counts: Counter[str] = Counter()
    for node in nodes:
        if isinstance(node, dict):
            label = str(node.get("label") or node.get("type") or "Unknown")
            label_counts[label] += 1

    top_labels = ", ".join(f"{label} ({count})" for label, count in label_counts.most_common(6))
    return (
        f"Investigation graph contains {len(nodes)} nodes and {len(edges)} relationships. "
        f"Node types: {top_labels}."
    )


def _build_executive_summary(
    *,
    title: str,
    root_cause: str,
    confidence: float,
    ticket_key: str,
    service_name: str,
    multi_agent_summary: str,
) -> str:
    parts = [f"Investigation: {title}."]
    if ticket_key:
        parts.append(f"Ticket: {ticket_key}.")
    if service_name:
        parts.append(f"Service: {service_name}.")
    if root_cause:
        parts.append(f"Root cause candidate: {root_cause}.")
    if confidence > 0:
        parts.append(f"RCA confidence: {confidence:.2f}.")
    if multi_agent_summary:
        parts.append(multi_agent_summary)
    return " ".join(parts)


def _similar_to_entry(item: SimilarInvestigation) -> SimilarIncidentEntry:
    return SimilarIncidentEntry(
        investigation_id=item.investigation_id,
        similarity_score=item.similarity_score,
        root_cause=item.root_cause,
        confidence=item.confidence,
        resolution_summary=item.resolution_summary,
        matched_factors=list(item.matched_factors),
    )


def _feedback_to_entry(record: FeedbackRecord) -> FeedbackHistoryEntry:
    return FeedbackHistoryEntry(
        feedback_id=record.feedback_id,
        candidate_id=record.candidate_id,
        feedback_type=record.feedback_type,
        comments=record.comments,
        user_id=record.user_id,
        created_at=record.created_at,
    )


def _runbook_to_entry(record: GraphRunbookRecord) -> RunbookEntry:
    return RunbookEntry(
        title=record.title,
        service_name=record.service_name,
        summary=record.summary,
        url=record.url,
    )


def _build_remediation_steps(
    runbooks: list[GraphRunbookRecord],
    known_issues: list,
    multi_agent_report: MultiAgentInvestigationReport,
) -> list[str]:
    steps: list[str] = []

    for runbook in runbooks[:5]:
        if runbook.summary:
            steps.append(f"Follow runbook '{runbook.title}': {runbook.summary}")
        elif runbook.title:
            steps.append(f"Review runbook '{runbook.title}' for {runbook.service_name or 'the affected service'}.")

    for issue in known_issues[:3]:
        workaround = getattr(issue, "workaround", "") or ""
        title = getattr(issue, "title", "") or "Known issue"
        if workaround:
            steps.append(f"Apply known-issue workaround ({title}): {workaround}")

    for finding in (
        multi_agent_report.deployment_findings,
        multi_agent_report.infrastructure_findings,
        multi_agent_report.incident_findings,
        multi_agent_report.knowledge_findings,
    ):
        for item in finding.suspicious_items[:2]:
            steps.append(f"Investigate ({finding.agent_name}): {item}")

    if not steps:
        steps.append("Review timeline, graph context, and similar incidents before remediation.")
    return list(dict.fromkeys(steps))[:12]


def build_investigation_report(
    client: Neo4jClient,
    investigation_id: str,
) -> InvestigationReport:
    """Gather investigation data and build a unified report object."""
    context = load_agent_investigation_context(client, investigation_id)
    findings = run_agents(context)
    multi_agent_report = build_multi_agent_report(context, findings)

    store_record = context.store_record if isinstance(context.store_record, dict) else {}
    root_cause = _resolve_root_cause(store_record)
    confidence, confidence_reasoning = _resolve_confidence(store_record)
    title = _resolve_title(store_record, investigation_id)

    return InvestigationReport(
        investigation_id=investigation_id,
        title=title,
        executive_summary=_build_executive_summary(
            title=title,
            root_cause=root_cause,
            confidence=confidence,
            ticket_key=context.ticket_key,
            service_name=context.service_name,
            multi_agent_summary=multi_agent_report.final_summary,
        ),
        timeline_summary=_build_timeline_summary(context.timeline_events),
        graph_summary=_build_graph_summary(client, investigation_id),
        root_cause=root_cause,
        confidence=confidence,
        confidence_reasoning=confidence_reasoning,
        similar_incidents=[_similar_to_entry(item) for item in context.similar_investigations],
        feedback_history=[_feedback_to_entry(item) for item in context.feedback],
        runbooks=[_runbook_to_entry(item) for item in context.runbooks],
        remediation_steps=_build_remediation_steps(
            context.runbooks,
            context.known_issues,
            multi_agent_report,
        ),
        multi_agent_summary=multi_agent_report.final_summary,
        evidence_coverage=_resolve_evidence_coverage(store_record),
        generated_at=_utc_now_iso(),
    )
