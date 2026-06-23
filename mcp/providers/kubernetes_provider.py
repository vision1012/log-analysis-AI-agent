"""Kubernetes MCP provider — normalized pods, nodes, namespaces, deployments, events."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from mcp.config import MCPFetchParams, kubernetes_mcp_enabled
from mcp.context.context_builder import merge_context
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.providers.base import BaseMCPProvider
from mcp.schemas.common import ProviderHealth, SourceMetadata
from mcp.schemas.kubernetes_models import (
    ClusterEvent,
    ContainerEvent,
    NamespaceEvent,
    NodeEvent,
    PodEvent,
)

logger = logging.getLogger(__name__)


class KubernetesProvider(BaseMCPProvider):
    source = "kubernetes"

    def is_enabled(self) -> bool:
        return kubernetes_mcp_enabled()

    def is_configured(self) -> bool:
        try:
            _k8s_cfg(allow_missing=False)
            return True
        except RuntimeError:
            return False

    def health_check(self) -> ProviderHealth:
        enabled = self.is_enabled()
        try:
            _k8s_cfg(allow_missing=False)
            configured = True
        except RuntimeError:
            configured = False

        if not enabled:
            return ProviderHealth(
                source="kubernetes",
                enabled=False,
                configured=configured,
                reachable=False,
                detail="disabled",
            )
        if not configured:
            return ProviderHealth(
                source="kubernetes",
                enabled=True,
                configured=False,
                reachable=False,
                detail="missing KUBERNETES_API_SERVER/token or kubeconfig",
            )
        try:
            cfg = _k8s_cfg(allow_missing=False)
            _k8s_get(cfg, "/version")
            return ProviderHealth(source="kubernetes", enabled=True, configured=True, reachable=True, detail="ok")
        except Exception as exc:
            return ProviderHealth(
                source="kubernetes",
                enabled=True,
                configured=True,
                reachable=False,
                detail=str(exc)[:200],
            )

    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        try:
            cfg = _k8s_cfg(allow_missing=False)
        except RuntimeError:
            return UnifiedInvestigationContext()

        namespace = _resolve_namespace(params, cfg)
        cluster_events, namespace_events = _fetch_events(cfg, namespace=namespace)
        pod_events, container_events = _fetch_pods(cfg, namespace=namespace)
        node_events = _fetch_nodes(cfg)
        _enrich_from_deployments(cfg, namespace=namespace, pod_events=pod_events)

        meta = SourceMetadata(
            source="kubernetes",
            fetched_at=datetime.now(timezone.utc),
            ok=True,
            detail=(
                f"cluster={cfg['cluster_name']} ns={namespace} pods={len(pod_events)} "
                f"containers={len(container_events)} nodes={len(node_events)}"
            ),
        )
        return merge_context(
            UnifiedInvestigationContext(),
            cluster_events=cluster_events,
            namespace_events=namespace_events,
            pod_events=pod_events,
            container_events=container_events,
            node_events=node_events,
            source_metadata=meta,
        )


def _resolve_namespace(params: MCPFetchParams, cfg: dict[str, str]) -> str:
    return (os.environ.get("KUBERNETES_NAMESPACE") or cfg.get("namespace") or "default").strip()


def _k8s_cfg(*, allow_missing: bool) -> dict[str, str]:
    api_server = (os.environ.get("KUBERNETES_API_SERVER") or "").strip()
    token = (os.environ.get("KUBERNETES_TOKEN") or "").strip()
    cluster_name = (os.environ.get("KUBERNETES_CLUSTER_NAME") or "").strip()
    namespace = (os.environ.get("KUBERNETES_NAMESPACE") or "").strip()
    context_name = (os.environ.get("KUBERNETES_CONTEXT") or "").strip()

    if not api_server or not token:
        loaded = _load_kubeconfig(context_name=context_name)
        api_server = api_server or loaded.get("api_server", "")
        token = token or loaded.get("token", "")
        cluster_name = cluster_name or loaded.get("cluster_name", "")
        namespace = namespace or loaded.get("namespace", "")

    if not api_server or not token:
        if allow_missing:
            return {}
        raise RuntimeError("Kubernetes MCP config incomplete")

    return {
        "api_server": api_server.rstrip("/"),
        "token": token,
        "cluster_name": cluster_name or context_name or "kubernetes",
        "cluster_id": cluster_name or context_name or api_server,
        "namespace": namespace,
        "ca_cert": (os.environ.get("KUBERNETES_CA_CERT") or "").strip(),
    }


def _load_kubeconfig(*, context_name: str) -> dict[str, str]:
    path = os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/config"))
    cfg_path = Path(path)
    if not cfg_path.is_file():
        return {}

    text = cfg_path.read_text(encoding="utf-8")
    if text.lstrip().startswith("{"):
        try:
            return _parse_kubeconfig_json(json.loads(text), context_name=context_name)
        except json.JSONDecodeError:
            return {}

    current = context_name or _kubeconfig_scalar(text, "current-context")
    if not current:
        return {}

    cluster_ref = _kubeconfig_context_cluster(text, current)
    user_ref = _kubeconfig_context_user(text, current)
    ns = _kubeconfig_context_namespace(text, current)
    server = _kubeconfig_cluster_server(text, cluster_ref)
    token = _kubeconfig_user_token(text, user_ref)
    return {
        "api_server": server,
        "token": token,
        "cluster_name": cluster_ref or current,
        "namespace": ns,
    }


def _parse_kubeconfig_json(doc: dict[str, Any], *, context_name: str) -> dict[str, str]:
    current = context_name or str(doc.get("current-context") or "")
    contexts = {c.get("name"): c.get("context") or {} for c in doc.get("contexts") or [] if isinstance(c, dict)}
    clusters = {c.get("name"): c.get("cluster") or {} for c in doc.get("clusters") or [] if isinstance(c, dict)}
    users = {u.get("name"): u.get("user") or {} for u in doc.get("users") or [] if isinstance(u, dict)}
    ctx = contexts.get(current) or {}
    cluster = clusters.get(ctx.get("cluster")) or {}
    user = users.get(ctx.get("user")) or {}
    return {
        "api_server": str(cluster.get("server") or ""),
        "token": str(user.get("token") or ""),
        "cluster_name": str(ctx.get("cluster") or current),
        "namespace": str(ctx.get("namespace") or ""),
    }


def _kubeconfig_scalar(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else ""


def _kubeconfig_context_cluster(text: str, context_name: str) -> str:
    block = _kubeconfig_context_block(text, context_name)
    return _kubeconfig_scalar(block, "cluster")


def _kubeconfig_context_user(text: str, context_name: str) -> str:
    block = _kubeconfig_context_block(text, context_name)
    return _kubeconfig_scalar(block, "user")


def _kubeconfig_context_namespace(text: str, context_name: str) -> str:
    block = _kubeconfig_context_block(text, context_name)
    return _kubeconfig_scalar(block, "namespace")


def _kubeconfig_context_block(text: str, context_name: str) -> str:
    pattern = rf"- context:\s*\n((?:[ \t]+[^\n]+\n)+?)\s+name:\s*{re.escape(context_name)}\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1) if match else ""


def _kubeconfig_cluster_server(text: str, cluster_name: str) -> str:
    if not cluster_name:
        return ""
    pattern = rf"- cluster:\s*\n(?:[ \t]+[^\n]+\n)+?\s+name:\s*{re.escape(cluster_name)}\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return ""
    server_match = re.search(r"server:\s*(\S+)", match.group(0))
    return server_match.group(1) if server_match else ""


def _kubeconfig_user_token(text: str, user_name: str) -> str:
    if not user_name:
        return ""
    pattern = rf"- name:\s*{re.escape(user_name)}\s*\n\s+user:\s*\n(?:[ \t]+[^\n]+\n)+"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return ""
    token_match = re.search(r"token:\s*(\S+)", match.group(0))
    return token_match.group(1) if token_match else ""


def _k8s_get(cfg: dict[str, str], path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    q = ""
    if query:
        q = "?" + parse.urlencode({k: v for k, v in query.items() if v})
    url = f"{cfg['api_server']}{path}{q}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {cfg['token']}",
    }
    req = request.Request(url, headers=headers, method="GET")
    timeout = int(os.environ.get("KUBERNETES_TIMEOUT_SEC", "15"))
    context = None
    ca_cert = cfg.get("ca_cert") or ""
    if ca_cert and not ca_cert.startswith("-----BEGIN"):
        try:
            ca_bytes = base64.b64decode(ca_cert)
            context = ssl.create_default_context(cadata=ca_bytes.decode("utf-8"))
        except Exception:
            context = ssl.create_default_context()
    with request.urlopen(req, timeout=timeout, context=context) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}


def _fetch_events(
    cfg: dict[str, str],
    *,
    namespace: str,
) -> tuple[list[ClusterEvent], list[NamespaceEvent]]:
    cluster_events: list[ClusterEvent] = []
    namespace_events: list[NamespaceEvent] = []
    try:
        payload = _k8s_get(cfg, f"/api/v1/namespaces/{namespace}/events")
    except urlerror.HTTPError:
        return cluster_events, namespace_events

    items = payload.get("items") or []
    if not isinstance(items, list):
        return cluster_events, namespace_events

    for item in items[:50]:
        if not isinstance(item, dict):
            continue
        ns_event = _normalize_event_item(item, namespace=namespace)
        if ns_event:
            namespace_events.append(ns_event)
        if str(item.get("type") or "").lower() == "warning":
            cluster_events.append(
                ClusterEvent(
                    cluster_name=cfg["cluster_name"],
                    cluster_id=cfg["cluster_id"],
                    timestamp=ns_event.timestamp if ns_event else None,
                    event_type=str(item.get("reason") or item.get("type") or ""),
                    message=str(item.get("message") or ""),
                )
            )
    return cluster_events[:20], namespace_events[:50]


def _normalize_event_item(item: dict[str, Any], *, namespace: str) -> NamespaceEvent | None:
    message = str(item.get("message") or "").strip()
    if not message:
        return None
    last = item.get("lastTimestamp") or item.get("eventTime") or item.get("firstTimestamp")
    return NamespaceEvent(
        namespace=namespace,
        timestamp=str(last) if last else None,
        event_type=str(item.get("reason") or item.get("type") or ""),
        message=message,
    )


def _fetch_pods(cfg: dict[str, str], *, namespace: str) -> tuple[list[PodEvent], list[ContainerEvent]]:
    pod_events: list[PodEvent] = []
    container_events: list[ContainerEvent] = []
    try:
        payload = _k8s_get(cfg, f"/api/v1/namespaces/{namespace}/pods")
    except urlerror.HTTPError:
        return pod_events, container_events

    items = payload.get("items") or []
    if not isinstance(items, list):
        return pod_events, container_events

    for item in items[:50]:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata") or {}
        spec = item.get("spec") or {}
        status = item.get("status") or {}
        pod_name = str(meta.get("name") or "")
        restart_count = 0
        pod_reason = str(status.get("reason") or status.get("phase") or "")
        pod_status = str(status.get("phase") or "")

        container_statuses = status.get("containerStatuses") or []
        if isinstance(container_statuses, list):
            for cs in container_statuses:
                if not isinstance(cs, dict):
                    continue
                restart_count = max(restart_count, int(cs.get("restartCount") or 0))
                state = cs.get("state") or {}
                waiting = state.get("waiting") or {}
                terminated = state.get("terminated") or {}
                reason = str(waiting.get("reason") or terminated.get("reason") or "")
                c_status = "waiting" if waiting else ("terminated" if terminated else "running")
                container_events.append(
                    ContainerEvent(
                        container_name=str(cs.get("name") or ""),
                        pod_name=pod_name,
                        image=str(cs.get("image") or ""),
                        status=c_status,
                        reason=reason,
                        timestamp=str(meta.get("creationTimestamp") or "") or None,
                    )
                )
                if reason in {"CrashLoopBackOff", "OOMKilled", "Error"}:
                    pod_reason = reason

        pod_events.append(
            PodEvent(
                pod_name=pod_name,
                namespace=namespace,
                node_name=str(spec.get("nodeName") or ""),
                status=pod_status,
                restart_count=restart_count,
                reason=pod_reason,
                timestamp=str(meta.get("creationTimestamp") or "") or None,
            )
        )
    return pod_events, container_events


def _fetch_nodes(cfg: dict[str, str]) -> list[NodeEvent]:
    try:
        payload = _k8s_get(cfg, "/api/v1/nodes")
    except urlerror.HTTPError:
        return []

    items = payload.get("items") or []
    if not isinstance(items, list):
        return []

    out: list[NodeEvent] = []
    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata") or {}
        status = item.get("status") or {}
        conditions = status.get("conditions") or []
        node_status = "Ready"
        for cond in conditions:
            if isinstance(cond, dict) and cond.get("type") == "Ready":
                node_status = str(cond.get("status") or node_status)
        alloc = status.get("allocatable") or {}
        cpu = _parse_cpu(str(alloc.get("cpu") or "0"))
        memory = _parse_memory(str(alloc.get("memory") or "0"))
        out.append(
            NodeEvent(
                node_name=str(meta.get("name") or ""),
                status=node_status,
                cpu_usage=cpu,
                memory_usage=memory,
                timestamp=str(meta.get("creationTimestamp") or "") or None,
            )
        )
    return out


def _enrich_from_deployments(cfg: dict[str, str], *, namespace: str, pod_events: list[PodEvent]) -> None:
    try:
        payload = _k8s_get(cfg, f"/apis/apps/v1/namespaces/{namespace}/deployments")
    except urlerror.HTTPError:
        return
    items = payload.get("items") or []
    if not isinstance(items, list):
        return
    failed_deployments = []
    for item in items:
        if not isinstance(item, dict):
            continue
        status = item.get("status") or {}
        desired = int(status.get("replicas") or 0)
        available = int(status.get("availableReplicas") or 0)
        if desired > 0 and available < desired:
            meta = item.get("metadata") or {}
            failed_deployments.append(str(meta.get("name") or ""))
    for pod in pod_events:
        if any(dep and dep in pod.pod_name for dep in failed_deployments):
            if pod.reason in {"", "Running", "Pending"}:
                pod.reason = "FailedDeployment"


def _parse_cpu(value: str) -> float:
    raw = (value or "").strip()
    if raw.endswith("m"):
        try:
            return float(raw[:-1]) / 1000.0
        except ValueError:
            return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _parse_memory(value: str) -> float:
    raw = (value or "").strip()
    multipliers = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}
    for suffix, mult in multipliers.items():
        if raw.endswith(suffix):
            try:
                return float(raw[: -len(suffix)]) * mult
            except ValueError:
                return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0
