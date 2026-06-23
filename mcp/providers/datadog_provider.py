"""Datadog MCP provider — normalized metrics, alerts, traces, and service health."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from mcp.config import MCPFetchParams, datadog_mcp_enabled
from mcp.context.context_builder import merge_context
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.providers.base import BaseMCPProvider
from mcp.schemas.common import ProviderHealth, SourceMetadata
from mcp.schemas.datadog_models import AlertEvent, MetricEvent, ServiceHealthEvent, TraceEvent

logger = logging.getLogger(__name__)

_DEFAULT_METRICS = (
    ("cpu_usage", "avg:system.cpu.user{service:%s}"),
    ("memory_usage", "avg:system.mem.used{service:%s}"),
    ("error_rate", "sum:trace.servlet.request.errors{service:%s}.as_rate()"),
    ("request_latency", "avg:trace.servlet.request.duration{service:%s}"),
    ("request_count", "sum:trace.servlet.request.hits{service:%s}.as_rate()"),
)


class DatadogProvider(BaseMCPProvider):
    source = "datadog"

    def is_enabled(self) -> bool:
        return datadog_mcp_enabled()

    def is_configured(self) -> bool:
        try:
            _datadog_cfg(allow_missing=False)
            return True
        except RuntimeError:
            return False

    def health_check(self) -> ProviderHealth:
        enabled = self.is_enabled()
        try:
            _datadog_cfg(allow_missing=False)
            configured = True
        except RuntimeError:
            configured = False

        if not enabled:
            return ProviderHealth(
                source="datadog",
                enabled=False,
                configured=configured,
                reachable=False,
                detail="disabled",
            )
        if not configured:
            return ProviderHealth(
                source="datadog",
                enabled=True,
                configured=False,
                reachable=False,
                detail="missing DATADOG_API_KEY, DATADOG_APP_KEY, or DATADOG_SITE",
            )
        try:
            cfg = _datadog_cfg(allow_missing=False)
            _datadog_get(cfg, "/api/v1/monitor", {"page_size": "1"})
            return ProviderHealth(source="datadog", enabled=True, configured=True, reachable=True, detail="ok")
        except Exception as exc:
            return ProviderHealth(
                source="datadog",
                enabled=True,
                configured=True,
                reachable=False,
                detail=str(exc)[:200],
            )

    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        try:
            cfg = _datadog_cfg(allow_missing=False)
        except RuntimeError:
            return UnifiedInvestigationContext()

        service = (params.service_name or os.environ.get("DATADOG_DEFAULT_SERVICE") or "").strip()
        start_ts, end_ts = _resolve_window(params)

        metrics = _fetch_metrics(cfg, service=service, start_ts=start_ts, end_ts=end_ts)
        alerts = _fetch_alerts(cfg, service=service, start_ts=start_ts, end_ts=end_ts)
        traces = _fetch_traces(cfg, service=service, start_ts=start_ts, end_ts=end_ts)
        health = _build_service_health(metrics, service=service)

        meta = SourceMetadata(
            source="datadog",
            fetched_at=datetime.now(timezone.utc),
            ok=True,
            detail=(
                f"service={service or '*'} metrics={len(metrics)} alerts={len(alerts)} "
                f"traces={len(traces)} health={len(health)}"
            ),
        )
        return merge_context(
            UnifiedInvestigationContext(),
            metric_events=metrics,
            alert_events=alerts,
            trace_events=traces,
            service_health_events=health,
            source_metadata=meta,
        )


def _datadog_cfg(*, allow_missing: bool) -> dict[str, str]:
    api_key = (os.environ.get("DATADOG_API_KEY") or "").strip()
    app_key = (os.environ.get("DATADOG_APP_KEY") or "").strip()
    site = (os.environ.get("DATADOG_SITE") or "datadoghq.com").strip().lstrip(".")
    if not api_key or not app_key or not site:
        if allow_missing:
            return {}
        raise RuntimeError("Datadog MCP config incomplete")
    return {
        "api_key": api_key,
        "app_key": app_key,
        "site": site,
        "base_url": f"https://api.{site}",
    }


def _datadog_headers(cfg: dict[str, str]) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "DD-API-KEY": cfg["api_key"],
        "DD-APPLICATION-KEY": cfg["app_key"],
    }


def _datadog_get(cfg: dict[str, str], path: str, query: dict[str, str] | None = None) -> Any:
    q = ""
    if query:
        q = "?" + parse.urlencode({k: v for k, v in query.items() if v})
    url = f"{cfg['base_url']}{path}{q}"
    req = request.Request(url, headers=_datadog_headers(cfg), method="GET")
    timeout = int(os.environ.get("DATADOG_TIMEOUT_SEC", "15"))
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _datadog_post(cfg: dict[str, str], path: str, body: dict[str, Any]) -> Any:
    url = f"{cfg['base_url']}{path}"
    payload = json.dumps(body).encode("utf-8")
    headers = _datadog_headers(cfg)
    req = request.Request(url, data=payload, headers=headers, method="POST")
    timeout = int(os.environ.get("DATADOG_TIMEOUT_SEC", "15"))
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_window(params: MCPFetchParams) -> tuple[int, int]:
    end = _iso_to_epoch(params.end_time) or int(datetime.now(timezone.utc).timestamp())
    start = _iso_to_epoch(params.start_time)
    if start is None:
        lookback = int(os.environ.get("DATADOG_LOOKBACK_MINUTES", "60"))
        start = end - lookback * 60
    if start >= end:
        start = end - 3600
    return start, end


def _iso_to_epoch(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def _epoch_to_iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _service_filter(service: str) -> str:
    return service if service else "*"


def _fetch_metrics(
    cfg: dict[str, str],
    *,
    service: str,
    start_ts: int,
    end_ts: int,
) -> list[MetricEvent]:
    svc = _service_filter(service)
    out: list[MetricEvent] = []
    for metric_name, query_tpl in _DEFAULT_METRICS:
        query = query_tpl % svc
        try:
            payload = _datadog_post(
                cfg,
                "/api/v1/query",
                {"from": start_ts, "to": end_ts, "query": query},
            )
        except urlerror.HTTPError:
            continue
        out.extend(_normalize_metric_series(metric_name, payload, service=service))
    return out[:100]


def _normalize_metric_series(metric_name: str, payload: dict[str, Any], *, service: str) -> list[MetricEvent]:
    series_list = payload.get("series")
    if not isinstance(series_list, list):
        return []
    events: list[MetricEvent] = []
    for series in series_list:
        if not isinstance(series, dict):
            continue
        pointlist = series.get("pointlist") or []
        scope = str(series.get("scope") or "")
        tags = [t.strip() for t in scope.split(",") if t.strip()]
        svc = service or _tag_value(tags, "service")
        unit = str(series.get("unit") or "")
        for point in pointlist[-10:]:
            if not isinstance(point, list) or len(point) < 2:
                continue
            ts_ms, value = point[0], point[1]
            if value is None:
                continue
            val = float(value)
            severity = _metric_severity(metric_name, val)
            events.append(
                MetricEvent(
                    metric_name=metric_name,
                    service=svc,
                    value=val,
                    unit=unit,
                    severity=severity,
                    timestamp=_epoch_to_iso(int(ts_ms / 1000)),
                    tags=tags,
                )
            )
    spike_events = [e for e in events if e.severity in {"warning", "high", "critical"}]
    return spike_events or events[-3:]


def _metric_severity(metric_name: str, value: float) -> str:
    if metric_name == "error_rate":
        if value >= 5.0:
            return "critical"
        if value >= 1.0:
            return "high"
        return "info"
    if metric_name == "cpu_usage":
        if value >= 90.0:
            return "critical"
        if value >= 75.0:
            return "high"
        if value >= 60.0:
            return "warning"
        return "info"
    if metric_name == "memory_usage":
        if value >= 90.0:
            return "critical"
        if value >= 80.0:
            return "high"
        return "info"
    if metric_name == "request_latency":
        if value >= 2000.0:
            return "critical"
        if value >= 1000.0:
            return "high"
        if value >= 500.0:
            return "warning"
        return "info"
    return "info"


def _tag_value(tags: list[str], key: str) -> str:
    prefix = f"{key}:"
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix) :]
    return ""


def _fetch_alerts(
    cfg: dict[str, str],
    *,
    service: str,
    start_ts: int,
    end_ts: int,
) -> list[AlertEvent]:
    query: dict[str, str] = {
        "start": str(start_ts),
        "end": str(end_ts),
        "limit": "50",
        "sources": "monitor",
    }
    if service:
        query["tags"] = f"service:{service}"
    try:
        payload = _datadog_get(cfg, "/api/v1/events", query)
    except urlerror.HTTPError:
        return []
    events = payload.get("events") if isinstance(payload, dict) else []
    if not isinstance(events, list):
        return []

    monitors = _fetch_monitors(cfg)
    monitor_by_id = {str(m.get("id")): m for m in monitors if isinstance(m, dict) and m.get("id") is not None}

    out: list[AlertEvent] = []
    for ev in events[:50]:
        if not isinstance(ev, dict):
            continue
        alert_id = str(ev.get("id") or ev.get("monitor_id") or "")
        monitor = monitor_by_id.get(str(ev.get("monitor_id") or ""), {})
        title = str(ev.get("title") or monitor.get("name") or "")
        message = str(ev.get("text") or ev.get("msg_text") or "")
        tags = ev.get("tags") or monitor.get("tags") or []
        svc = service or _tag_value([str(t) for t in tags], "service")
        out.append(
            AlertEvent(
                alert_id=alert_id,
                title=title,
                message=message,
                severity=str(ev.get("priority") or monitor.get("type") or "normal"),
                service=svc,
                status=str(ev.get("alert_type") or ev.get("status") or "triggered"),
                triggered_at=_epoch_to_iso(int(ev.get("date_happened") or start_ts)),
                resolved_at=None,
            )
        )
    return out


def _fetch_monitors(cfg: dict[str, str]) -> list[dict[str, Any]]:
    try:
        payload = _datadog_get(cfg, "/api/v1/monitor", {"page_size": "50"})
    except urlerror.HTTPError:
        return []
    return payload if isinstance(payload, list) else []


def _fetch_traces(
    cfg: dict[str, str],
    *,
    service: str,
    start_ts: int,
    end_ts: int,
) -> list[TraceEvent]:
    trace_query = "status:error"
    if service:
        trace_query = f"service:{service} status:error"
    body = {
        "data": {
            "type": "search_request",
            "attributes": {
                "filter": {
                    "from": _epoch_to_iso(start_ts),
                    "to": _epoch_to_iso(end_ts),
                    "query": trace_query,
                },
                "page": {"limit": 30},
            },
        }
    }
    try:
        payload = _datadog_post(cfg, "/api/v2/spans/events/search", body)
    except urlerror.HTTPError:
        return []

    data = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(data, list):
        return []

    out: list[TraceEvent] = []
    for item in data[:30]:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes") or {}
        custom = attrs.get("custom") or {}
        out.append(
            TraceEvent(
                trace_id=str(item.get("id") or attrs.get("trace_id") or ""),
                service=str(custom.get("service") or attrs.get("service") or service),
                endpoint=str(custom.get("http.url") or custom.get("resource_name") or ""),
                latency_ms=float(custom.get("duration") or attrs.get("duration") or 0.0) / 1_000_000.0
                if float(custom.get("duration") or attrs.get("duration") or 0.0) > 10_000
                else float(custom.get("duration") or attrs.get("duration") or 0.0),
                error_count=1 if str(attrs.get("status") or custom.get("status") or "") == "error" else 0,
                timestamp=str(attrs.get("timestamp") or attrs.get("start") or "") or _epoch_to_iso(start_ts),
            )
        )
    return out


def _build_service_health(metrics: list[MetricEvent], *, service: str) -> list[ServiceHealthEvent]:
    if not metrics and not service:
        return []
    by_service: dict[str, dict[str, float]] = {}
    latest_ts: dict[str, str] = {}
    for metric in metrics:
        svc = metric.service or service or "unknown"
        bucket = by_service.setdefault(svc, {})
        bucket[metric.metric_name] = metric.value
        if metric.timestamp:
            latest_ts[svc] = metric.timestamp

    out: list[ServiceHealthEvent] = []
    for svc, values in by_service.items():
        error_rate = float(values.get("error_rate", 0.0))
        latency = float(values.get("request_latency", 0.0))
        cpu = float(values.get("cpu_usage", 0.0))
        memory = float(values.get("memory_usage", 0.0))
        status = _health_status(error_rate=error_rate, cpu=cpu, memory=memory, latency=latency)
        out.append(
            ServiceHealthEvent(
                service_name=svc,
                health_status=status,
                error_rate=error_rate,
                latency=latency,
                cpu_usage=cpu,
                memory_usage=memory,
                timestamp=latest_ts.get(svc),
            )
        )
    return out


def _health_status(*, error_rate: float, cpu: float, memory: float, latency: float) -> str:
    if error_rate >= 5.0 or cpu >= 90.0 or memory >= 90.0 or latency >= 2000.0:
        return "unhealthy"
    if error_rate >= 1.0 or cpu >= 75.0 or memory >= 80.0 or latency >= 1000.0:
        return "degraded"
    return "healthy"
