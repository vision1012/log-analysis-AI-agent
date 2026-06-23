"""Correlate Confluence knowledge docs with tickets, alerts, pods, and incidents."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.common import InvestigationCorrelation, SourceMetadata
from mcp.schemas.confluence_models import ArchitectureDocument, KnownIssueDocument, RunbookDocument
from mcp.schemas.datadog_models import AlertEvent
from mcp.schemas.jira_models import McpTicketContext
from mcp.schemas.kubernetes_models import PodEvent
from mcp.schemas.pagerduty_models import PagerDutyIncidentEvent


def correlate_knowledge_and_attach_metadata(
    context: UnifiedInvestigationContext,
) -> UnifiedInvestigationContext:
    """Append knowledge-base correlation metadata; RCA ranking unchanged."""
    correlations = correlate_knowledge(context)
    if not correlations:
        return context

    meta = SourceMetadata(
        source="correlator",
        fetched_at=datetime.now(timezone.utc),
        ok=True,
        detail=f"knowledge_links={len(correlations)}",
        correlations=correlations,
    )
    data = context.model_dump()
    data["source_metadata"] = list(data.get("source_metadata") or []) + [meta.model_dump()]
    return UnifiedInvestigationContext.model_validate(data)


def correlate_knowledge(context: UnifiedInvestigationContext) -> list[InvestigationCorrelation]:
    """Return service/runbook, alert/known-issue, pod/known-issue, incident/SOP, service/architecture links."""
    links: list[InvestigationCorrelation] = []
    ticket = context.ticket_context

    for runbook in context.runbook_documents:
        links.extend(_correlate_runbook(runbook, ticket, context.pagerduty_incidents))

    for known_issue in context.known_issue_documents:
        links.extend(_correlate_known_issue(known_issue, ticket, context.alert_events, context.pod_events))

    for arch_doc in context.architecture_documents:
        links.extend(_correlate_architecture(arch_doc, ticket))

    return links


def _correlate_runbook(
    runbook: RunbookDocument,
    ticket: McpTicketContext | None,
    incidents: list[PagerDutyIncidentEvent],
) -> list[InvestigationCorrelation]:
    links: list[InvestigationCorrelation] = []
    doc_ref = f"runbook:{runbook.document_id or runbook.title[:32]}"

    service_names = _collect_service_names(ticket, runbook.service_name)
    for service in service_names:
        if _service_match(service, runbook.service_name) or _text_match(service, runbook.title, runbook.summary):
            links.append(
                InvestigationCorrelation(
                    relation="service_to_runbook",
                    from_ref=f"service:{service}",
                    to_ref=doc_ref,
                    document_id=runbook.document_id,
                    service_name=service,
                )
            )

    for incident in incidents:
        if not _is_sop_runbook(runbook):
            continue
        if _text_match(incident.title, runbook.title, runbook.summary) or _service_match(
            incident.service_name, runbook.service_name
        ):
            links.append(
                InvestigationCorrelation(
                    relation="incident_to_sop",
                    from_ref=f"incident:{incident.incident_id or incident.incident_number}",
                    to_ref=doc_ref,
                    document_id=runbook.document_id,
                    incident_id=incident.incident_id,
                    service_name=incident.service_name or runbook.service_name,
                )
            )

    if ticket and _ticket_matches_doc(ticket, runbook.title, runbook.summary, runbook.labels):
        links.append(
            InvestigationCorrelation(
                relation="service_to_runbook",
                from_ref=f"ticket:{ticket.issue_key}",
                to_ref=doc_ref,
                document_id=runbook.document_id,
                service_name=runbook.service_name,
            )
        )

    return links


def _correlate_known_issue(
    known_issue: KnownIssueDocument,
    ticket: McpTicketContext | None,
    alerts: list[AlertEvent],
    pods: list[PodEvent],
) -> list[InvestigationCorrelation]:
    links: list[InvestigationCorrelation] = []
    doc_ref = f"known_issue:{known_issue.document_id or known_issue.title[:32]}"

    for alert in alerts:
        if not _alert_matches_known_issue(alert, known_issue):
            continue
        links.append(
            InvestigationCorrelation(
                relation="alert_to_known_issue",
                from_ref=f"alert:{alert.alert_id or alert.title[:32]}",
                to_ref=doc_ref,
                document_id=known_issue.document_id,
                alert_id=alert.alert_id,
                service_name=known_issue.affected_service or alert.service,
            )
        )

    for pod in pods:
        if not _pod_matches_known_issue(pod, known_issue):
            continue
        links.append(
            InvestigationCorrelation(
                relation="pod_error_to_known_issue",
                from_ref=f"pod:{pod.pod_name or pod.reason}",
                to_ref=doc_ref,
                document_id=known_issue.document_id,
                pod_name=pod.pod_name,
                service_name=known_issue.affected_service,
            )
        )

    if ticket and _ticket_matches_known_issue(ticket, known_issue):
        links.append(
            InvestigationCorrelation(
                relation="alert_to_known_issue",
                from_ref=f"ticket:{ticket.issue_key}",
                to_ref=doc_ref,
                document_id=known_issue.document_id,
                service_name=known_issue.affected_service,
            )
        )

    return links


def _correlate_architecture(
    arch_doc: ArchitectureDocument,
    ticket: McpTicketContext | None,
) -> list[InvestigationCorrelation]:
    links: list[InvestigationCorrelation] = []
    doc_ref = f"architecture:{arch_doc.document_id or arch_doc.title[:32]}"
    service_names = _collect_service_names(ticket, arch_doc.service_name)

    for service in service_names:
        if _service_match(service, arch_doc.service_name) or _text_match(service, arch_doc.title, arch_doc.summary):
            links.append(
                InvestigationCorrelation(
                    relation="service_to_architecture_doc",
                    from_ref=f"service:{service}",
                    to_ref=doc_ref,
                    document_id=arch_doc.document_id,
                    service_name=service,
                )
            )

    if ticket and _ticket_matches_doc(ticket, arch_doc.title, arch_doc.summary, arch_doc.components):
        links.append(
            InvestigationCorrelation(
                relation="service_to_architecture_doc",
                from_ref=f"ticket:{ticket.issue_key}",
                to_ref=doc_ref,
                document_id=arch_doc.document_id,
                service_name=arch_doc.service_name,
            )
        )

    return links


def _is_sop_runbook(runbook: RunbookDocument) -> bool:
    labels = {lbl.lower() for lbl in runbook.labels}
    if labels & {"sop", "incident"}:
        return True
    title = runbook.title.lower()
    return "sop" in title or "incident response" in title


def _alert_matches_known_issue(alert: AlertEvent, known_issue: KnownIssueDocument) -> bool:
    if _service_match(alert.service, known_issue.affected_service):
        return True
    alert_text = f"{alert.title} {alert.message}".lower()
    for kw in known_issue.error_keywords:
        if kw and kw.lower() in alert_text:
            return True
    return _text_match(alert.title, known_issue.title, known_issue.workaround)


def _pod_matches_known_issue(pod: PodEvent, known_issue: KnownIssueDocument) -> bool:
    pod_text = f"{pod.reason} {pod.status} {pod.pod_name}".lower()
    for kw in known_issue.error_keywords:
        if kw and kw.lower() in pod_text:
            return True
    if pod.reason and pod.reason.lower() in known_issue.title.lower():
        return True
    return False


def _ticket_matches_known_issue(ticket: McpTicketContext, known_issue: KnownIssueDocument) -> bool:
    ticket_text = f"{ticket.summary} {ticket.description}".lower()
    if known_issue.affected_service and known_issue.affected_service.lower() in ticket_text:
        return True
    for kw in known_issue.error_keywords:
        if kw and kw.lower() in ticket_text:
            return True
    return False


def _ticket_matches_doc(
    ticket: McpTicketContext,
    title: str,
    body: str,
    labels_or_keywords: list[str],
) -> bool:
    ticket_text = f"{ticket.summary} {ticket.description}".lower()
    if _text_match(ticket.summary, title, body):
        return True
    for item in labels_or_keywords:
        token = (item or "").strip().lower()
        if token and token in ticket_text:
            return True
    for label in ticket.labels:
        if label.lower() in {lbl.lower() for lbl in labels_or_keywords}:
            return True
    return False


def _collect_service_names(ticket: McpTicketContext | None, *extras: str) -> list[str]:
    names: list[str] = []
    for value in extras:
        s = (value or "").strip()
        if s and s not in names:
            names.append(s)
    if ticket:
        ticket_text = f"{ticket.summary} {ticket.description}".lower()
        for match in re.finditer(r"\b([a-z][a-z0-9-]*-service)\b", ticket_text):
            svc = match.group(1)
            if svc not in names:
                names.append(svc)
    return names


def _service_match(a: str, b: str) -> bool:
    left = (a or "").strip().lower()
    right = (b or "").strip().lower()
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _text_match(*parts: str) -> bool:
    tokens = [(p or "").strip().lower() for p in parts if (p or "").strip()]
    if len(tokens) < 2:
        return False
    anchor = tokens[0]
    for other in tokens[1:]:
        if anchor in other or other in anchor:
            return True
        anchor_words = {w for w in anchor.split() if len(w) > 3}
        other_words = {w for w in other.split() if len(w) > 3}
        if anchor_words & other_words:
            return True
    return False
