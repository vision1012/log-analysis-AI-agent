"""Correlate Datadog alerts with PagerDuty incidents and escalation timeline."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.common import InvestigationCorrelation, SourceMetadata
from mcp.schemas.datadog_models import AlertEvent
from mcp.schemas.pagerduty_models import PagerDutyEscalationEvent, PagerDutyIncidentEvent, PagerDutyTimelineEvent


def correlation_window_minutes() -> int:
    raw = (os.environ.get("PAGERDUTY_CORRELATION_WINDOW_MINUTES") or "30").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 30


def correlate_alert_incident_and_attach_metadata(
    context: UnifiedInvestigationContext,
) -> UnifiedInvestigationContext:
    """Append alert↔incident correlation metadata; RCA ranking unchanged."""
    correlations = correlate_alert_incident(context)
    if not correlations:
        return context

    meta = SourceMetadata(
        source="correlator",
        fetched_at=datetime.now(timezone.utc),
        ok=True,
        detail=f"pagerduty_links={len(correlations)}",
        correlations=correlations,
    )
    data = context.model_dump()
    data["source_metadata"] = list(data.get("source_metadata") or []) + [meta.model_dump()]
    return UnifiedInvestigationContext.model_validate(data)


def correlate_alert_incident(context: UnifiedInvestigationContext) -> list[InvestigationCorrelation]:
    """Return alert→incident and incident lifecycle links."""
    window = timedelta(minutes=correlation_window_minutes())
    links: list[InvestigationCorrelation] = []

    for alert in context.alert_events:
        alert_time = _parse_ts(alert.triggered_at)
        if alert_time is None:
            continue
        for incident in context.pagerduty_incidents:
            inc_time = _parse_ts(incident.created_at)
            if inc_time is None:
                continue
            if not (alert_time <= inc_time <= alert_time + window):
                continue
            if not _service_match(alert.service, incident.service_name):
                continue
            links.append(
                InvestigationCorrelation(
                    relation="alert_to_pagerduty_incident",
                    from_ref=f"alert:{alert.alert_id or alert.title[:32]}",
                    to_ref=f"incident:{incident.incident_id or incident.incident_number}",
                    alert_id=alert.alert_id,
                    incident_id=incident.incident_id,
                    service_name=incident.service_name or alert.service,
                )
            )

    for incident in context.pagerduty_incidents:
        inc_ref = f"incident:{incident.incident_id or incident.incident_number}"

        if incident.service_name:
            links.append(
                InvestigationCorrelation(
                    relation="pagerduty_incident_to_service",
                    from_ref=inc_ref,
                    to_ref=f"service:{incident.service_name}",
                    incident_id=incident.incident_id,
                    service_name=incident.service_name,
                )
            )

        for esc in context.pagerduty_escalations:
            if esc.incident_id != incident.incident_id:
                continue
            links.append(
                InvestigationCorrelation(
                    relation="pagerduty_incident_to_escalation",
                    from_ref=inc_ref,
                    to_ref=f"escalation:{esc.escalation_policy_id or esc.responder_name}",
                    incident_id=incident.incident_id,
                    escalation_policy_id=esc.escalation_policy_id,
                    responder_name=esc.responder_name,
                )
            )

        if incident.status == "resolved" and incident.resolved_at:
            links.append(
                InvestigationCorrelation(
                    relation="pagerduty_incident_to_resolved",
                    from_ref=inc_ref,
                    to_ref=f"resolved:{incident.resolved_at}",
                    incident_id=incident.incident_id,
                    service_name=incident.service_name,
                )
            )

        for event in context.pagerduty_timeline_events:
            if event.incident_id != incident.incident_id:
                continue
            if event.event_type in {"acknowledge_log_entry", "responder_request_log_entry"}:
                links.append(
                    InvestigationCorrelation(
                        relation="pagerduty_incident_to_escalation",
                        from_ref=inc_ref,
                        to_ref=f"timeline:{event.event_id or event.event_type}",
                        incident_id=incident.incident_id,
                        responder_name=event.actor_name,
                    )
                )

    return links


def _service_match(alert_service: str, incident_service: str) -> bool:
    a = (alert_service or "").strip().lower()
    b = (incident_service or "").strip().lower()
    if not a or not b:
        return True
    return a == b or a in b or b in a


def _parse_ts(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None
