"""Normalized graph retrieval result models."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class GraphDeploymentRecord(BaseModel):
    """Deployment node retrieved from the investigation graph."""

    deployment_id: str = ""
    environment: str = ""
    status: str = ""
    commit_sha: str = ""
    deployed_at: Optional[str] = None
    deployment_url: str = ""
    service_name: str = ""
    investigation_id: str = ""


class GraphIncidentRecord(BaseModel):
    """PagerDuty incident retrieved from the investigation graph."""

    incident_id: str = ""
    incident_number: int = 0
    title: str = ""
    service_name: str = ""
    urgency: str = ""
    status: str = ""
    created_at: Optional[str] = None
    resolved_at: Optional[str] = None
    html_url: str = ""
    alert_id: str = ""
    investigation_id: str = ""


class GraphAlertRecord(BaseModel):
    """Monitor alert retrieved from the investigation graph."""

    alert_id: str = ""
    title: str = ""
    message: str = ""
    severity: str = ""
    service: str = ""
    status: str = ""
    triggered_at: Optional[str] = None
    resolved_at: Optional[str] = None
    investigation_id: str = ""


class GraphCommitRecord(BaseModel):
    """Commit node retrieved from the investigation graph."""

    sha: str = ""
    message: str = ""
    author: str = ""
    committed_at: Optional[str] = None
    repo_ref: str = ""
    service_name: str = ""


class GraphKnownIssueRecord(BaseModel):
    """Known-issue document retrieved from the investigation graph."""

    known_issue_id: str = ""
    title: str = ""
    affected_service: str = ""
    workaround: str = ""
    severity: str = ""
    url: str = ""
    alert_id: str = ""


class GraphRunbookRecord(BaseModel):
    """Runbook document retrieved from the investigation graph."""

    runbook_id: str = ""
    title: str = ""
    service_name: str = ""
    summary: str = ""
    url: str = ""
    space_key: str = ""
    updated_at: Optional[str] = None


class GraphInvestigationRecord(BaseModel):
    """Prior investigation retrieved for similarity lookup."""

    investigation_id: str = ""
    ticket_key: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    similarity_score: float = 0.0
    shared_service: str = ""
    match_reason: str = ""


class SimilarInvestigation(BaseModel):
    """Historical investigation similar to the current investigation context."""

    investigation_id: str
    similarity_score: float = 0.0
    matched_factors: List[str] = Field(default_factory=list)
    root_cause: str = ""
    confidence: float = 0.0
    resolution_summary: str = ""
    created_at: Optional[str] = None
