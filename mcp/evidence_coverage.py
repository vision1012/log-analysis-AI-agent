"""
Investigation evidence coverage — track which MCP sources contributed context.

Read-only analysis of UnifiedInvestigationContext; does not change RCA or provider fetch behavior.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from mcp.connection_manager import validate_all_connections
from mcp.connection_models import MCPConnectionStatus
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.registry import registered_sources
from mcp.schemas.common import MCPSourceName
from mcp.schemas.github_models import McpCommit
from mcp.schemas.gitlab_models import McpGitLabCommit
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent

logger = logging.getLogger(__name__)

CoverageLevel = Literal["low", "partial", "good", "high"]


class SourceDetail(BaseModel):
    """Per-provider configuration, health, and contribution status."""

    configured: bool = False
    healthy: bool = False
    contributed: bool = False


class EvidenceCoverage(BaseModel):
    """Summary of which MCP evidence sources contributed to an investigation."""

    available_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    available_source_count: int = 0
    missing_source_count: int = 0
    coverage_score: float = 0.0
    coverage_level: CoverageLevel = "low"
    source_details: dict[str, SourceDetail] = Field(default_factory=dict)


def _coverage_level(score: float) -> CoverageLevel:
    if score < 0.25:
        return "low"
    if score < 0.50:
        return "partial"
    if score < 0.75:
        return "good"
    return "high"


def _connection_status_map(workspace_id: str = "") -> dict[MCPSourceName, MCPConnectionStatus]:
    try:
        statuses = validate_all_connections(workspace_id=workspace_id or None)
        return {status.provider: status for status in statuses}
    except Exception as exc:
        logger.warning("mcp.evidence_coverage.connection_status_failed err=%s", exc)
        return {}


def _source_detail(
    source: MCPSourceName,
    *,
    contributed: bool,
    statuses: dict[MCPSourceName, MCPConnectionStatus],
) -> SourceDetail:
    status = statuses.get(source)
    if status is None:
        return SourceDetail(configured=False, healthy=False, contributed=contributed)
    return SourceDetail(
        configured=status.configured,
        healthy=status.healthy,
        contributed=contributed,
    )


def _contributed_jira(context: UnifiedInvestigationContext) -> bool:
    return context.ticket_context is not None


def _contributed_github(context: UnifiedInvestigationContext) -> bool:
    if context.pull_requests:
        return True
    return any(isinstance(commit, McpCommit) for commit in context.commits)


def _contributed_gitlab(context: UnifiedInvestigationContext) -> bool:
    if context.merge_requests:
        return True
    return any(isinstance(commit, McpGitLabCommit) for commit in context.commits)


def _contributed_jenkins(context: UnifiedInvestigationContext) -> bool:
    if context.build_events:
        return True
    return any(isinstance(event, DeploymentEvent) for event in context.deployment_events)


def _contributed_datadog(context: UnifiedInvestigationContext) -> bool:
    return bool(context.alert_events or context.metric_events or context.trace_events)


def _contributed_kubernetes(context: UnifiedInvestigationContext) -> bool:
    return bool(context.pod_events or context.container_events or context.node_events)


def _contributed_pagerduty(context: UnifiedInvestigationContext) -> bool:
    return bool(context.pagerduty_incidents)


def _contributed_confluence(context: UnifiedInvestigationContext) -> bool:
    return bool(
        context.runbook_documents
        or context.known_issue_documents
        or context.architecture_documents
    )


_CONTRIBUTION_CHECKS: dict[MCPSourceName, Any] = {
    "jira": _contributed_jira,
    "github": _contributed_github,
    "gitlab": _contributed_gitlab,
    "jenkins": _contributed_jenkins,
    "datadog": _contributed_datadog,
    "kubernetes": _contributed_kubernetes,
    "pagerduty": _contributed_pagerduty,
    "confluence": _contributed_confluence,
}


def compute_evidence_coverage(
    context: UnifiedInvestigationContext,
    *,
    connection_statuses: dict[MCPSourceName, MCPConnectionStatus] | None = None,
    workspace_id: str = "",
) -> EvidenceCoverage:
    """
    Compute evidence coverage for a unified investigation context.

    Uses provider contribution rules and optional connection health metadata.
    """
    statuses = connection_statuses if connection_statuses is not None else _connection_status_map(workspace_id)
    sources = registered_sources()

    source_details: dict[str, SourceDetail] = {}
    available_sources: list[str] = []
    missing_sources: list[str] = []

    for source in sources:
        contributed = _CONTRIBUTION_CHECKS[source](context)
        source_details[source] = _source_detail(source, contributed=contributed, statuses=statuses)
        if contributed:
            available_sources.append(source)
        else:
            missing_sources.append(source)

    total = len(sources)
    available_count = len(available_sources)
    missing_count = len(missing_sources)
    score = round(available_count / total, 4) if total else 0.0

    return EvidenceCoverage(
        available_sources=available_sources,
        missing_sources=missing_sources,
        available_source_count=available_count,
        missing_source_count=missing_count,
        coverage_score=score,
        coverage_level=_coverage_level(score),
        source_details=source_details,
    )


def attach_evidence_coverage(
    context: UnifiedInvestigationContext,
    *,
    workspace_id: str = "",
) -> UnifiedInvestigationContext:
    """Return context with evidence_coverage populated."""
    coverage = compute_evidence_coverage(context, workspace_id=workspace_id)
    return context.model_copy(update={"evidence_coverage": coverage})


def _rebuild_unified_context_model() -> None:
    UnifiedInvestigationContext.model_rebuild(_types_namespace={"EvidenceCoverage": EvidenceCoverage})


_rebuild_unified_context_model()
