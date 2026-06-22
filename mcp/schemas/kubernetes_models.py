"""Normalized Kubernetes infrastructure models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ClusterEvent(BaseModel):
    """Cluster-level Kubernetes event."""

    cluster_name: str = ""
    cluster_id: str = ""
    timestamp: Optional[str] = None
    event_type: str = ""
    message: str = ""


class NamespaceEvent(BaseModel):
    """Namespace-scoped Kubernetes event."""

    namespace: str = ""
    timestamp: Optional[str] = None
    event_type: str = ""
    message: str = ""


class PodEvent(BaseModel):
    """Normalized pod runtime state."""

    pod_name: str = ""
    namespace: str = ""
    node_name: str = ""
    status: str = ""
    restart_count: int = 0
    reason: str = ""
    timestamp: Optional[str] = None


class ContainerEvent(BaseModel):
    """Normalized container state within a pod."""

    container_name: str = ""
    pod_name: str = ""
    image: str = ""
    status: str = ""
    reason: str = ""
    timestamp: Optional[str] = None


class NodeEvent(BaseModel):
    """Normalized node health snapshot."""

    node_name: str = ""
    status: str = ""
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    timestamp: Optional[str] = None
