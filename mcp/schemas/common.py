"""Shared MCP schema types."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

MCPSourceName = Literal[
    "jira", "github", "gitlab", "jenkins", "datadog", "kubernetes", "pagerduty", "confluence"
]
MetadataSourceName = Literal[
    "jira",
    "github",
    "gitlab",
    "jenkins",
    "datadog",
    "kubernetes",
    "pagerduty",
    "confluence",
    "correlator",
]


class InvestigationCorrelation(BaseModel):
    """Normalized link between investigation artifacts (stored in source_metadata)."""

    relation: Literal[
        "commit_to_build",
        "build_to_deployment",
        "pr_to_commit",
        "deployment_to_metric_spike",
        "deployment_to_alert",
        "deployment_to_trace_failure",
        "metric_spike_to_alert",
        "deployment_to_pod_restart",
        "deployment_to_crash_loop",
        "deployment_to_oom_killed",
        "deployment_to_node_pressure",
        "pod_restart_to_alert",
        "alert_to_pagerduty_incident",
        "pagerduty_incident_to_escalation",
        "pagerduty_incident_to_resolved",
        "pagerduty_incident_to_service",
        "service_to_runbook",
        "alert_to_known_issue",
        "pod_error_to_known_issue",
        "incident_to_sop",
        "service_to_architecture_doc",
    ]
    from_ref: str
    to_ref: str
    document_id: str = ""
    commit_sha: str = ""
    build_number: Optional[int] = None
    deployment_id: str = ""
    environment: str = ""
    pr_number: Optional[int] = None
    metric_name: str = ""
    alert_id: str = ""
    trace_id: str = ""
    pod_name: str = ""
    container_name: str = ""
    node_name: str = ""
    incident_id: str = ""
    service_name: str = ""
    escalation_policy_id: str = ""
    responder_name: str = ""


class SourceMetadata(BaseModel):
    """Provenance for a normalized MCP payload slice."""

    source: MetadataSourceName
    fetched_at: datetime
    ok: bool = True
    detail: str = ""
    correlations: List[InvestigationCorrelation] = Field(default_factory=list)


class ProviderHealth(BaseModel):
    """Health probe result for one MCP provider."""

    source: MCPSourceName
    enabled: bool
    configured: bool
    reachable: bool
    detail: str = ""
