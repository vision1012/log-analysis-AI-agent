"""Normalized PagerDuty incident-management models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PagerDutyIncidentEvent(BaseModel):
    """Normalized PagerDuty incident."""

    incident_id: str = ""
    incident_number: int = 0
    title: str = ""
    description: str = ""
    service_name: str = ""
    urgency: str = ""
    status: str = ""
    created_at: Optional[str] = None
    acknowledged_at: Optional[str] = None
    resolved_at: Optional[str] = None
    html_url: str = ""


class PagerDutyEscalationEvent(BaseModel):
    """Normalized escalation / responder assignment."""

    escalation_policy_id: str = ""
    escalation_policy_name: str = ""
    incident_id: str = ""
    responder_name: str = ""
    responder_email: str = ""
    assigned_at: Optional[str] = None
    acknowledged_at: Optional[str] = None


class PagerDutyTimelineEvent(BaseModel):
    """Normalized incident timeline / log entry."""

    event_id: str = ""
    incident_id: str = ""
    event_type: str = ""
    summary: str = ""
    created_at: Optional[str] = None
    actor_name: str = ""
