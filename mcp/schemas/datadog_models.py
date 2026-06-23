"""Normalized Datadog observability models."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class MetricEvent(BaseModel):
    """Normalized metric observation or spike."""

    metric_name: str = ""
    service: str = ""
    value: float = 0.0
    unit: str = ""
    severity: str = ""
    timestamp: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class AlertEvent(BaseModel):
    """Normalized monitor alert event."""

    alert_id: str = ""
    title: str = ""
    message: str = ""
    severity: str = ""
    service: str = ""
    status: str = ""
    triggered_at: Optional[str] = None
    resolved_at: Optional[str] = None


class TraceEvent(BaseModel):
    """Normalized APM trace summary."""

    trace_id: str = ""
    service: str = ""
    endpoint: str = ""
    latency_ms: float = 0.0
    error_count: int = 0
    timestamp: Optional[str] = None


class ServiceHealthEvent(BaseModel):
    """Aggregated service health snapshot."""

    service_name: str = ""
    health_status: str = ""
    error_rate: float = 0.0
    latency: float = 0.0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    timestamp: Optional[str] = None
