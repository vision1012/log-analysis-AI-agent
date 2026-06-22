"""Multi-agent investigation models."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from feedback.feedback_models import FeedbackRecord
from graph.retrieval_models import (
    GraphAlertRecord,
    GraphDeploymentRecord,
    GraphIncidentRecord,
    GraphKnownIssueRecord,
    GraphRunbookRecord,
    SimilarInvestigation,
)
from investigation.timeline_models import InvestigationTimelineEvent


class AgentInvestigationContext(BaseModel):
    """Read-only investigation context shared across specialized agents."""

    investigation_id: str
    ticket_key: str = ""
    service_name: str = ""
    timeline_events: List[InvestigationTimelineEvent] = Field(default_factory=list)
    deployments: List[GraphDeploymentRecord] = Field(default_factory=list)
    builds: List[dict[str, Any]] = Field(default_factory=list)
    alerts: List[GraphAlertRecord] = Field(default_factory=list)
    incidents: List[GraphIncidentRecord] = Field(default_factory=list)
    runbooks: List[GraphRunbookRecord] = Field(default_factory=list)
    known_issues: List[GraphKnownIssueRecord] = Field(default_factory=list)
    similar_investigations: List[SimilarInvestigation] = Field(default_factory=list)
    feedback: List[FeedbackRecord] = Field(default_factory=list)
    store_record: dict[str, Any] = Field(default_factory=dict)


class AgentFinding(BaseModel):
    """Findings contributed by one specialized investigation agent."""

    agent_name: str
    summary: str
    key_observations: List[str] = Field(default_factory=list)
    suspicious_items: List[str] = Field(default_factory=list)
    correlations: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    evidence: dict[str, Any] = Field(default_factory=dict)


class MultiAgentInvestigationReport(BaseModel):
    """Merged output from all specialized investigation agents."""

    investigation_id: str
    timeline_findings: AgentFinding
    deployment_findings: AgentFinding
    infrastructure_findings: AgentFinding
    incident_findings: AgentFinding
    knowledge_findings: AgentFinding
    rca_findings: AgentFinding
    final_summary: str
