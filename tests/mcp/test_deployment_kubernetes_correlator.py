"""Tests for deployment ↔ Kubernetes correlator."""

from __future__ import annotations

import pytest

from mcp.context.deployment_kubernetes_correlator import (
    correlate_deployment_kubernetes,
    correlate_deployment_kubernetes_and_attach_metadata,
)
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.datadog_models import AlertEvent
from mcp.schemas.jenkins_models import DeploymentEvent
from mcp.schemas.kubernetes_models import ContainerEvent, NodeEvent, PodEvent


@pytest.fixture
def correlation_window(monkeypatch):
    monkeypatch.setenv("KUBERNETES_CORRELATION_WINDOW_MINUTES", "30")


def _sample_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext(
        deployment_events=[
            DeploymentEvent(
                deployment_id="jenkins-deploy:99:production",
                environment="production",
                status="SUCCESS",
                commit_sha="abc123",
                build_number=99,
                deployed_at="2024-01-01T14:10:00Z",
                deployment_url="https://jenkins/job/app/99/",
            )
        ],
        pod_events=[
            PodEvent(
                pod_name="payments-api-abc123",
                namespace="production",
                node_name="node-1",
                status="Running",
                restart_count=5,
                reason="CrashLoopBackOff",
                timestamp="2024-01-01T14:10:30Z",
            )
        ],
        container_events=[
            ContainerEvent(
                container_name="payments-api",
                pod_name="payments-api-abc123",
                image="payments:1.2.3",
                status="waiting",
                reason="OOMKilled",
                timestamp="2024-01-01T14:10:35Z",
            )
        ],
        node_events=[
            NodeEvent(
                node_name="node-1",
                status="False",
                cpu_usage=0.95,
                memory_usage=9 * 1024**3,
                timestamp="2024-01-01T14:10:00Z",
            )
        ],
        alert_events=[
            AlertEvent(
                alert_id="alert-88",
                title="Pod restart storm",
                message="restart count exceeded",
                severity="high",
                service="payments-api",
                status="triggered",
                triggered_at="2024-01-01T14:11:00Z",
            )
        ],
    )


def test_correlator_links_deployment_kubernetes_events(correlation_window):
    links = correlate_deployment_kubernetes(_sample_context())
    relations = {link.relation for link in links}
    assert "deployment_to_pod_restart" in relations
    assert "deployment_to_crash_loop" in relations
    assert "deployment_to_oom_killed" in relations
    assert "deployment_to_node_pressure" in relations
    assert "pod_restart_to_alert" in relations


def test_correlator_attaches_source_metadata(correlation_window):
    ctx = correlate_deployment_kubernetes_and_attach_metadata(_sample_context())
    k8s_meta = [m for m in ctx.source_metadata if m.detail.startswith("kubernetes_links=")]
    assert len(k8s_meta) == 1
    assert len(k8s_meta[0].correlations) >= 4


def test_correlator_ignores_pods_outside_window(correlation_window):
    ctx = _sample_context()
    ctx.pod_events[0].timestamp = "2024-01-01T16:00:00Z"
    links = correlate_deployment_kubernetes(ctx)
    dep_restart = [l for l in links if l.relation == "deployment_to_pod_restart"]
    assert dep_restart == []
