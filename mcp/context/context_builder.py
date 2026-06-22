"""Build and merge unified MCP investigation context."""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.context.investigation_context import UnifiedInvestigationContext
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
from schemas.jira import JiraExtractedHints


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def empty_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext()


def merge_context(
    base: UnifiedInvestigationContext,
    *,
    ticket_context: McpTicketContext | None = None,
    commits: list | None = None,
    pull_requests: list[McpPullRequest] | None = None,
    merge_requests: list[McpMergeRequest] | None = None,
    build_events: list[BuildEvent] | None = None,
    deployment_events: list[McpDeploymentEvent] | None = None,
    jenkins_deployment_events: list[DeploymentEvent] | None = None,
    metric_events: list[MetricEvent] | None = None,
    alert_events: list[AlertEvent] | None = None,
    trace_events: list[TraceEvent] | None = None,
    service_health_events: list[ServiceHealthEvent] | None = None,
    cluster_events: list[ClusterEvent] | None = None,
    namespace_events: list[NamespaceEvent] | None = None,
    pod_events: list[PodEvent] | None = None,
    container_events: list[ContainerEvent] | None = None,
    node_events: list[NodeEvent] | None = None,
    pipelines: list[McpPipeline] | None = None,
    source_metadata: SourceMetadata | None = None,
) -> UnifiedInvestigationContext:
    """Return a new context with provider slices merged in."""
    data = base.model_dump()
    if ticket_context is not None:
        data["ticket_context"] = ticket_context.model_dump()
    if commits:
        data["commits"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in commits]
    if pull_requests:
        data["pull_requests"] = [p.model_dump() for p in pull_requests]
    if merge_requests:
        data["merge_requests"] = [m.model_dump() for m in merge_requests]
    if build_events:
        data["build_events"] = [b.model_dump() for b in build_events]
    merged_deployments = list(data.get("deployment_events") or [])
    if deployment_events:
        merged_deployments.extend([d.model_dump() for d in deployment_events])
    if jenkins_deployment_events:
        merged_deployments.extend([d.model_dump() for d in jenkins_deployment_events])
    if merged_deployments != list(data.get("deployment_events") or []):
        data["deployment_events"] = merged_deployments
    if metric_events:
        data["metric_events"] = list(data.get("metric_events") or []) + [m.model_dump() for m in metric_events]
    if alert_events:
        data["alert_events"] = list(data.get("alert_events") or []) + [a.model_dump() for a in alert_events]
    if trace_events:
        data["trace_events"] = list(data.get("trace_events") or []) + [t.model_dump() for t in trace_events]
    if service_health_events:
        data["service_health_events"] = list(data.get("service_health_events") or []) + [
            s.model_dump() for s in service_health_events
        ]
    if cluster_events:
        data["cluster_events"] = list(data.get("cluster_events") or []) + [c.model_dump() for c in cluster_events]
    if namespace_events:
        data["namespace_events"] = list(data.get("namespace_events") or []) + [n.model_dump() for n in namespace_events]
    if pod_events:
        data["pod_events"] = list(data.get("pod_events") or []) + [p.model_dump() for p in pod_events]
    if container_events:
        data["container_events"] = list(data.get("container_events") or []) + [
            c.model_dump() for c in container_events
        ]
    if node_events:
        data["node_events"] = list(data.get("node_events") or []) + [n.model_dump() for n in node_events]
    if pipelines:
        data["pipelines"] = [p.model_dump() for p in pipelines]
    if source_metadata is not None:
        meta = list(data.get("source_metadata") or [])
        meta.append(source_metadata.model_dump())
        data["source_metadata"] = meta
    return UnifiedInvestigationContext.model_validate(data)


def enrich_ticket_hints(
    hints: JiraExtractedHints,
    context: UnifiedInvestigationContext,
) -> JiraExtractedHints:
    """
    Enrich deterministic ticket hints from normalized MCP context.

    Does not replace existing hints — only augments file paths, keywords, labels.
    """
    file_paths = list(hints.file_paths)
    error_keywords = list(hints.error_keywords)
    labels = list(hints.labels)
    service_names = list(hints.service_names)

    ticket = context.ticket_context
    if ticket:
        labels = _uniq(labels + ticket.labels)
        for comment in ticket.comments:
            error_keywords = _uniq(error_keywords + _keyword_hits(comment.body))
        for linked in ticket.linked_issues:
            error_keywords = _uniq(error_keywords + _keyword_hits(linked.summary))

    for pr in context.pull_requests:
        file_paths = _uniq(file_paths + pr.changed_files)
        error_keywords = _uniq(error_keywords + _keyword_hits(pr.title))

    for commit in context.commits:
        if isinstance(commit, McpCommit):
            file_paths = _uniq(file_paths + commit.changed_files)
            error_keywords = _uniq(error_keywords + _keyword_hits(commit.message))
        elif isinstance(commit, McpGitLabCommit):
            error_keywords = _uniq(error_keywords + _keyword_hits(commit.title))

    for dep in context.deployment_events:
        env = getattr(dep, "environment", "") or ""
        if env:
            envs = list(hints.environment_names)
            if env not in envs:
                envs.append(env)
            hints = hints.model_copy(update={"environment_names": envs})

    for alert in context.alert_events:
        error_keywords = _uniq(error_keywords + _keyword_hits(alert.title) + _keyword_hits(alert.message))
        if alert.service and alert.service not in service_names:
            service_names.append(alert.service)

    for metric in context.metric_events:
        if metric.service and metric.service not in service_names:
            service_names.append(metric.service)
        if metric.severity in {"high", "critical"}:
            error_keywords = _uniq(error_keywords + [metric.metric_name])

    for health in context.service_health_events:
        if health.service_name and health.service_name not in service_names:
            service_names.append(health.service_name)
        if health.health_status in {"degraded", "unhealthy"}:
            error_keywords = _uniq(error_keywords + ["degraded", health.health_status])

    for pod in context.pod_events:
        if pod.restart_count > 0:
            error_keywords = _uniq(error_keywords + ["pod_restart", "restart"])
        if pod.reason in {"CrashLoopBackOff", "FailedDeployment", "OOMKilled", "Error"}:
            error_keywords = _uniq(error_keywords + [pod.reason.lower(), pod.reason])

    for container in context.container_events:
        if container.reason in {"OOMKilled", "CrashLoopBackOff", "Error"}:
            error_keywords = _uniq(error_keywords + [container.reason.lower(), container.reason])

    for ns_event in context.namespace_events:
        error_keywords = _uniq(error_keywords + _keyword_hits(ns_event.message))

    for node in context.node_events:
        if node.status not in {"True", "Ready"}:
            error_keywords = _uniq(error_keywords + ["node_pressure", node.node_name])

    return hints.model_copy(
        update={
            "file_paths": file_paths[:100],
            "error_keywords": error_keywords[:50],
            "labels": labels[:50],
            "service_names": service_names,
        }
    )


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = (item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


_KEYWORD_BANK = ("error", "exception", "timeout", "failed", "panic", "outage", "rollback")


def _keyword_hits(text: str) -> list[str]:
    lower = (text or "").lower()
    return [k for k in _KEYWORD_BANK if k in lower]
