"""Correlate deployments with Datadog metric spikes, alerts, and trace failures."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.common import InvestigationCorrelation, SourceMetadata
from mcp.schemas.datadog_models import AlertEvent, MetricEvent, TraceEvent
from mcp.schemas.gitlab_models import McpDeploymentEvent
from mcp.schemas.jenkins_models import DeploymentEvent


def correlation_window_minutes() -> int:
    raw = (os.environ.get("DATADOG_CORRELATION_WINDOW_MINUTES") or "30").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 30


def correlate_deployment_observability_and_attach_metadata(
    context: UnifiedInvestigationContext,
) -> UnifiedInvestigationContext:
    """Append deployment→observability correlation metadata; RCA ranking unchanged."""
    correlations = correlate_deployment_observability(context)
    if not correlations:
        return context

    meta = SourceMetadata(
        source="correlator",
        fetched_at=datetime.now(timezone.utc),
        ok=True,
        detail=f"observability_links={len(correlations)}",
        correlations=correlations,
    )
    data = context.model_dump()
    data["source_metadata"] = list(data.get("source_metadata") or []) + [meta.model_dump()]
    return UnifiedInvestigationContext.model_validate(data)


def correlate_deployment_observability(
    context: UnifiedInvestigationContext,
) -> list[InvestigationCorrelation]:
    """Return deployment→metric/alert/trace and metric→alert links."""
    window = timedelta(minutes=correlation_window_minutes())
    links: list[InvestigationCorrelation] = []

    spike_metrics = [
        m
        for m in context.metric_events
        if m.severity in {"warning", "high", "critical"} or m.metric_name in {"error_rate", "cpu_usage"}
    ]

    for dep in context.deployment_events:
        dep_time = _parse_ts(_deployment_timestamp(dep))
        dep_id, env = _deployment_identity(dep)
        if dep_time is None:
            continue
        dep_ref = f"deployment:{dep_id or env}"

        for metric in spike_metrics:
            metric_time = _parse_ts(metric.timestamp)
            if metric_time is None:
                continue
            if dep_time <= metric_time <= dep_time + window:
                links.append(
                    InvestigationCorrelation(
                        relation="deployment_to_metric_spike",
                        from_ref=dep_ref,
                        to_ref=f"metric:{metric.metric_name}",
                        deployment_id=dep_id,
                        environment=env,
                        metric_name=metric.metric_name,
                    )
                )

        for alert in context.alert_events:
            alert_time = _parse_ts(alert.triggered_at)
            if alert_time is None:
                continue
            if dep_time <= alert_time <= dep_time + window:
                links.append(
                    InvestigationCorrelation(
                        relation="deployment_to_alert",
                        from_ref=dep_ref,
                        to_ref=f"alert:{alert.alert_id or alert.title[:32]}",
                        deployment_id=dep_id,
                        environment=env,
                        alert_id=alert.alert_id,
                    )
                )

        for trace in context.trace_events:
            if trace.error_count <= 0:
                continue
            trace_time = _parse_ts(trace.timestamp)
            if trace_time is None:
                continue
            if dep_time <= trace_time <= dep_time + window:
                links.append(
                    InvestigationCorrelation(
                        relation="deployment_to_trace_failure",
                        from_ref=dep_ref,
                        to_ref=f"trace:{trace.trace_id or trace.endpoint[:32]}",
                        deployment_id=dep_id,
                        environment=env,
                        trace_id=trace.trace_id,
                    )
                )

    for metric in spike_metrics:
        metric_time = _parse_ts(metric.timestamp)
        if metric_time is None:
            continue
        for alert in context.alert_events:
            alert_time = _parse_ts(alert.triggered_at)
            if alert_time is None:
                continue
            if metric_time <= alert_time <= metric_time + window:
                links.append(
                    InvestigationCorrelation(
                        relation="metric_spike_to_alert",
                        from_ref=f"metric:{metric.metric_name}",
                        to_ref=f"alert:{alert.alert_id or alert.title[:32]}",
                        metric_name=metric.metric_name,
                        alert_id=alert.alert_id,
                    )
                )
    return links


def _deployment_timestamp(dep: DeploymentEvent | McpDeploymentEvent) -> str | None:
    if isinstance(dep, DeploymentEvent):
        return dep.deployed_at
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
