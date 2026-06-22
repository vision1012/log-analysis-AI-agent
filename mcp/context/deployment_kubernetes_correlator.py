"""Correlate deployments with Kubernetes pod, container, and node events."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.common import InvestigationCorrelation, SourceMetadata
from mcp.schemas.datadog_models import AlertEvent
from mcp.schemas.gitlab_models import McpDeploymentEvent
from mcp.schemas.jenkins_models import DeploymentEvent
from mcp.schemas.kubernetes_models import ContainerEvent, NodeEvent, PodEvent


def correlation_window_minutes() -> int:
    raw = (os.environ.get("KUBERNETES_CORRELATION_WINDOW_MINUTES") or "30").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 30


def correlate_deployment_kubernetes_and_attach_metadata(
    context: UnifiedInvestigationContext,
) -> UnifiedInvestigationContext:
    """Append deployment→Kubernetes correlation metadata; RCA ranking unchanged."""
    correlations = correlate_deployment_kubernetes(context)
    if not correlations:
        return context

    meta = SourceMetadata(
        source="correlator",
        fetched_at=datetime.now(timezone.utc),
        ok=True,
        detail=f"kubernetes_links={len(correlations)}",
        correlations=correlations,
    )
    data = context.model_dump()
    data["source_metadata"] = list(data.get("source_metadata") or []) + [meta.model_dump()]
    return UnifiedInvestigationContext.model_validate(data)


def correlate_deployment_kubernetes(context: UnifiedInvestigationContext) -> list[InvestigationCorrelation]:
    """Return deployment→pod/container/node and pod-restart→alert links."""
    window = timedelta(minutes=correlation_window_minutes())
    links: list[InvestigationCorrelation] = []

    restart_pods = [p for p in context.pod_events if p.restart_count > 0]
    crash_pods = {p.pod_name for p in context.pod_events if p.reason == "CrashLoopBackOff"}
    oom_containers = {
        (c.pod_name, c.container_name)
        for c in context.container_events
        if c.reason == "OOMKilled" or "oom" in c.reason.lower()
    }
    pressured_nodes = {
        n.node_name
        for n in context.node_events
        if n.status not in {"True", "Ready"} or n.cpu_usage >= 0.9 or n.memory_usage >= 8 * 1024**3
    }

    for dep in context.deployment_events:
        dep_time = _parse_ts(_deployment_timestamp(dep))
        dep_id, env = _deployment_identity(dep)
        if dep_time is None:
            continue
        dep_ref = f"deployment:{dep_id or env}"

        for pod in context.pod_events:
            pod_time = _parse_ts(pod.timestamp)
            if pod_time is None or not (dep_time <= pod_time <= dep_time + window):
                continue

            if pod.restart_count > 0:
                links.append(
                    InvestigationCorrelation(
                        relation="deployment_to_pod_restart",
                        from_ref=dep_ref,
                        to_ref=f"pod:{pod.pod_name}",
                        deployment_id=dep_id,
                        environment=env,
                        pod_name=pod.pod_name,
                    )
                )

            if pod.pod_name in crash_pods or pod.reason == "CrashLoopBackOff":
                links.append(
                    InvestigationCorrelation(
                        relation="deployment_to_crash_loop",
                        from_ref=dep_ref,
                        to_ref=f"pod:{pod.pod_name}",
                        deployment_id=dep_id,
                        environment=env,
                        pod_name=pod.pod_name,
                    )
                )

            for container in context.container_events:
                if container.pod_name != pod.pod_name:
                    continue
                if (container.pod_name, container.container_name) in oom_containers:
                    links.append(
                        InvestigationCorrelation(
                            relation="deployment_to_oom_killed",
                            from_ref=dep_ref,
                            to_ref=f"container:{container.container_name}",
                            deployment_id=dep_id,
                            environment=env,
                            pod_name=pod.pod_name,
                            container_name=container.container_name,
                        )
                    )

            if pod.node_name in pressured_nodes:
                links.append(
                    InvestigationCorrelation(
                        relation="deployment_to_node_pressure",
                        from_ref=dep_ref,
                        to_ref=f"node:{pod.node_name}",
                        deployment_id=dep_id,
                        environment=env,
                        pod_name=pod.pod_name,
                        node_name=pod.node_name,
                    )
                )

    for pod in restart_pods:
        pod_time = _parse_ts(pod.timestamp)
        if pod_time is None:
            continue
        for alert in context.alert_events:
            alert_time = _parse_ts(alert.triggered_at)
            if alert_time is None:
                continue
            if pod_time <= alert_time <= pod_time + window:
                links.append(
                    InvestigationCorrelation(
                        relation="pod_restart_to_alert",
                        from_ref=f"pod:{pod.pod_name}",
                        to_ref=f"alert:{alert.alert_id or alert.title[:32]}",
                        pod_name=pod.pod_name,
                        alert_id=alert.alert_id,
                    )
                )
    return links


def _deployment_timestamp(dep: DeploymentEvent | McpDeploymentEvent) -> str | None:
    return dep.deployed_at


def _deployment_identity(dep: DeploymentEvent | McpDeploymentEvent) -> tuple[str, str]:
    if isinstance(dep, DeploymentEvent):
        return dep.deployment_id, dep.environment
    return dep.environment or dep.commit_sha[:12] if dep.commit_sha else "", dep.environment


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
