"""Unified investigation context returned by MCP orchestration."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from mcp.schemas.common import SourceMetadata
from mcp.schemas.datadog_models import AlertEvent, MetricEvent, ServiceHealthEvent, TraceEvent
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.gitlab_models import McpDeploymentEvent, McpGitLabCommit, McpMergeRequest, McpPipeline
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.jira_models import McpTicketContext
from mcp.schemas.kubernetes_models import (
    ClusterEvent,
    ContainerEvent,
    NamespaceEvent,
    NodeEvent,
    PodEvent,
)
from mcp.schemas.confluence_models import ArchitectureDocument, KnownIssueDocument, RunbookDocument
from mcp.schemas.pagerduty_models import (
    PagerDutyEscalationEvent,
    PagerDutyIncidentEvent,
    PagerDutyTimelineEvent,
)


class UnifiedInvestigationContext(BaseModel):
    """
    Provider-agnostic investigation context for signal enrichment.

    No raw provider payloads are exposed — only normalized objects.
    """

    ticket_context: Optional[McpTicketContext] = None
    commits: List[McpCommit | McpGitLabCommit] = Field(default_factory=list)
    pull_requests: List[McpPullRequest] = Field(default_factory=list)
    merge_requests: List[McpMergeRequest] = Field(default_factory=list)
    build_events: List[BuildEvent] = Field(default_factory=list)
    deployment_events: List[DeploymentEvent | McpDeploymentEvent] = Field(default_factory=list)
    metric_events: List[MetricEvent] = Field(default_factory=list)
    alert_events: List[AlertEvent] = Field(default_factory=list)
    trace_events: List[TraceEvent] = Field(default_factory=list)
    service_health_events: List[ServiceHealthEvent] = Field(default_factory=list)
    cluster_events: List[ClusterEvent] = Field(default_factory=list)
    namespace_events: List[NamespaceEvent] = Field(default_factory=list)
    pod_events: List[PodEvent] = Field(default_factory=list)
    container_events: List[ContainerEvent] = Field(default_factory=list)
    node_events: List[NodeEvent] = Field(default_factory=list)
    pagerduty_incidents: List[PagerDutyIncidentEvent] = Field(default_factory=list)
    pagerduty_escalations: List[PagerDutyEscalationEvent] = Field(default_factory=list)
    pagerduty_timeline_events: List[PagerDutyTimelineEvent] = Field(default_factory=list)
    runbook_documents: List[RunbookDocument] = Field(default_factory=list)
    known_issue_documents: List[KnownIssueDocument] = Field(default_factory=list)
    architecture_documents: List[ArchitectureDocument] = Field(default_factory=list)
    pipelines: List[McpPipeline] = Field(default_factory=list)
    source_metadata: List[SourceMetadata] = Field(default_factory=list)
    evidence_coverage: Optional["EvidenceCoverage"] = None
