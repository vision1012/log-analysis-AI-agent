"""Tests for Kubernetes MCP provider with mocked API responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mcp.config import MCPFetchParams
from mcp.providers.kubernetes_provider import KubernetesProvider


@pytest.fixture
def k8s_env(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("KUBERNETES_MCP_ENABLED", "true")
    monkeypatch.setenv("KUBERNETES_API_SERVER", "https://k8s.example.com")
    monkeypatch.setenv("KUBERNETES_TOKEN", "k8s-token")
    monkeypatch.setenv("KUBERNETES_NAMESPACE", "production")
    monkeypatch.setenv("KUBERNETES_CLUSTER_NAME", "prod-cluster")


def _mock_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _urlopen_side_effect():
    def _side_effect(req, timeout=15, context=None):
        url = req.full_url
        if url.endswith("/version"):
            return _mock_response({"gitVersion": "v1.29.0"})
        if "/events" in url:
            return _mock_response(
                {
                    "items": [
                        {
                            "type": "Warning",
                            "reason": "FailedScheduling",
                            "message": "0/3 nodes are available: insufficient memory",
                            "lastTimestamp": "2024-01-01T14:11:00Z",
                        }
                    ]
                }
            )
        if "/pods" in url:
            return _mock_response(
                {
                    "items": [
                        {
                            "metadata": {"name": "payments-api-abc123", "creationTimestamp": "2024-01-01T14:10:30Z"},
                            "spec": {"nodeName": "node-1"},
                            "status": {
                                "phase": "Running",
                                "reason": "CrashLoopBackOff",
                                "containerStatuses": [
                                    {
                                        "name": "payments-api",
                                        "image": "payments:1.2.3",
                                        "restartCount": 5,
                                        "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                                    }
                                ],
                            },
                        }
                    ]
                }
            )
        if "/nodes" in url:
            return _mock_response(
                {
                    "items": [
                        {
                            "metadata": {"name": "node-1", "creationTimestamp": "2024-01-01T00:00:00Z"},
                            "status": {
                                "conditions": [{"type": "Ready", "status": "False"}],
                                "allocatable": {"cpu": "4", "memory": "8Gi"},
                            },
                        }
                    ]
                }
            )
        if "/deployments" in url:
            return _mock_response(
                {
                    "items": [
                        {
                            "metadata": {"name": "payments-api"},
                            "status": {"replicas": 3, "availableReplicas": 1},
                        }
                    ]
                }
            )
        return _mock_response({})

    return _side_effect


@patch("mcp.providers.kubernetes_provider.request.urlopen")
def test_kubernetes_provider_fetch_normalizes_events(mock_urlopen, k8s_env):
    mock_urlopen.side_effect = _urlopen_side_effect()

    provider = KubernetesProvider()
    assert provider.is_enabled() is True
    assert provider.is_configured() is True

    ctx = provider.fetch(MCPFetchParams(ticket_key="OPS-10", service_name="payments-api"))
    assert len(ctx.pod_events) == 1
    pod = ctx.pod_events[0]
    assert pod.pod_name == "payments-api-abc123"
    assert pod.restart_count == 5
    assert pod.reason == "CrashLoopBackOff"

    assert len(ctx.container_events) == 1
    assert ctx.container_events[0].container_name == "payments-api"
    assert ctx.container_events[0].reason == "CrashLoopBackOff"

    assert len(ctx.namespace_events) == 1
    assert len(ctx.cluster_events) >= 1
    assert len(ctx.node_events) == 1
    assert ctx.source_metadata[0].source == "kubernetes"


@patch("mcp.providers.kubernetes_provider.request.urlopen")
def test_kubernetes_provider_health_check_ok(mock_urlopen, k8s_env):
    mock_urlopen.return_value = _mock_response({"gitVersion": "v1.29.0"})
    health = KubernetesProvider().health_check()
    assert health.source == "kubernetes"
    assert health.enabled is True
    assert health.configured is True
    assert health.reachable is True


def test_kubernetes_provider_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("KUBERNETES_MCP_ENABLED", "false")
    provider = KubernetesProvider()
    assert provider.is_enabled() is False


def test_kubernetes_provider_not_configured_without_credentials(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("KUBERNETES_MCP_ENABLED", "true")
    for key in ("KUBERNETES_API_SERVER", "KUBERNETES_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KUBECONFIG", "/nonexistent/kubeconfig")
    provider = KubernetesProvider()
    assert provider.is_configured() is False
    assert provider.fetch(MCPFetchParams(ticket_key="OPS-1")).pod_events == []
