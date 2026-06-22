"""
Centralized MCP connection validation with cached health checks.

Wraps provider ``is_configured()`` and ``health_check()`` without changing fetch behavior.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from mcp.connection_models import MCPConnectionStatus
from mcp.registry import get_provider_class, registered_sources
from mcp.schemas.common import MCPSourceName, ProviderHealth

DEFAULT_CACHE_SECONDS = 300

_cache: dict[MCPSourceName, MCPConnectionStatus] = {}
_cache_monotonic: float = 0.0


def _cache_seconds() -> int:
    raw = (os.environ.get("MCP_HEALTH_CACHE_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_CACHE_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_CACHE_SECONDS


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_provider(provider_name: str) -> MCPSourceName:
    key = (provider_name or "").strip().lower()
    if key not in registered_sources():
        raise KeyError(f"unknown MCP provider: {provider_name}")
    return key  # type: ignore[return-value]


def _health_to_connection_status(health: ProviderHealth) -> MCPConnectionStatus:
    healthy = bool(health.reachable)
    error_message: str | None = None

    if not health.configured:
        healthy = False
        error_message = health.detail or "not configured"
    elif not health.enabled:
        healthy = False
        error_message = health.detail or "disabled"
    elif not health.reachable:
        error_message = health.detail or "unreachable"
    elif health.detail and health.detail not in {"ok", ""}:
        error_message = health.detail

    return MCPConnectionStatus(
        provider=health.source,
        configured=health.configured,
        healthy=healthy,
        last_checked=_utc_now_iso(),
        error_message=error_message,
    )


def _is_cache_valid() -> bool:
    if not _cache:
        return False
    ttl = _cache_seconds()
    if ttl <= 0:
        return False
    return (time.monotonic() - _cache_monotonic) < ttl


def _store_cache(status: MCPConnectionStatus) -> None:
    global _cache_monotonic
    _cache[status.provider] = status
    _cache_monotonic = time.monotonic()


def clear_connection_cache() -> None:
    """Clear cached connection statuses (primarily for tests)."""
    global _cache_monotonic
    _cache.clear()
    _cache_monotonic = 0.0


def validate_provider(provider_name: str, *, force_refresh: bool = False) -> MCPConnectionStatus:
    """Validate one MCP provider connection."""
    name = _normalize_provider(provider_name)
    if not force_refresh and _is_cache_valid() and name in _cache:
        return _cache[name]

    provider = get_provider_class(name)()
    status = _health_to_connection_status(provider.health_check())
    _store_cache(status)
    return status


def validate_all_connections(*, force_refresh: bool = False) -> list[MCPConnectionStatus]:
    """Validate all registered MCP provider connections."""
    sources = registered_sources()
    if not force_refresh and _is_cache_valid() and all(source in _cache for source in sources):
        return [_cache[source] for source in sources]

    statuses = [validate_provider(source, force_refresh=True) for source in sources]
    return statuses
