"""
Centralized MCP connection validation with cached health checks.

Workspace-scoped validation uses ``integration_connections`` (encrypted credentials).
Environment credentials are only used when no workspace_id is supplied (local scripts).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from db.postgres.connection import get_db_session_readonly
from integrations.connection_repository import list_connections
from mcp.connection_models import MCPConnectionStatus
from mcp.integration_resolver import (
    resolve_runtime_connection_for_workspace,
    runtime_connection_from_row,
)
from mcp.registry import get_provider_class, registered_sources
from mcp.runtime_connection import ProviderRuntimeConnection
from mcp.schemas.common import MCPSourceName, ProviderHealth

DEFAULT_CACHE_SECONDS = 300

_cache: dict[str, MCPConnectionStatus] = {}
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


def _health_to_connection_status(
    health: ProviderHealth,
    *,
    connection_id: str | None = None,
    display_name: str | None = None,
) -> MCPConnectionStatus:
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
        connection_id=connection_id,
        display_name=display_name,
    )


def _is_cache_valid() -> bool:
    if not _cache:
        return False
    ttl = _cache_seconds()
    if ttl <= 0:
        return False
    return (time.monotonic() - _cache_monotonic) < ttl


def _store_cache(status: MCPConnectionStatus, *, cache_key: str) -> None:
    global _cache_monotonic
    _cache[cache_key] = status
    _cache_monotonic = time.monotonic()


def clear_connection_cache() -> None:
    """Clear cached connection statuses (primarily for tests)."""
    global _cache_monotonic
    _cache.clear()
    _cache_monotonic = 0.0


def _cache_key(
    *,
    workspace_id: str | None,
    provider: MCPSourceName,
    connection_id: str | None = None,
) -> str:
    scope = (workspace_id or "env").strip() or "env"
    if connection_id:
        return f"{scope}:{connection_id}"
    return f"{scope}:{provider}"


def _validate_runtime(
    provider_name: MCPSourceName,
    runtime: ProviderRuntimeConnection | None,
    *,
    database_only: bool,
    connection_id: str | None = None,
    display_name: str | None = None,
) -> MCPConnectionStatus:
    provider = get_provider_class(provider_name)(
        runtime_connection=runtime,
        database_only=database_only,
    )
    return _health_to_connection_status(
        provider.health_check(),
        connection_id=connection_id,
        display_name=display_name,
    )


def _list_enabled_workspace_connections(workspace_id: str) -> list[object]:
    ws = workspace_id.strip()
    with get_db_session_readonly() as session:
        rows = list_connections(session, ws)
        enabled = [row for row in rows if bool(getattr(row, "is_enabled", False))]
        for row in enabled:
            session.expunge(row)
        return enabled


def _validate_workspace_connections(
    workspace_id: str,
    *,
    force_refresh: bool = False,
) -> list[MCPConnectionStatus]:
    ws = workspace_id.strip()
    rows = _list_enabled_workspace_connections(ws)
    if not rows:
        return []

    statuses: list[MCPConnectionStatus] = []
    for row in rows:
        provider_raw = str(getattr(row, "provider", "") or "").strip().lower()
        if provider_raw not in registered_sources():
            continue
        provider = provider_raw  # type: ignore[assignment]
        connection_id = str(getattr(row, "id", "") or "")
        display_name = str(getattr(row, "display_name", "") or "") or None
        cache_key = _cache_key(
            workspace_id=ws,
            provider=provider,
            connection_id=connection_id or None,
        )
        if not force_refresh and _is_cache_valid() and cache_key in _cache:
            statuses.append(_cache[cache_key])
            continue

        runtime = runtime_connection_from_row(row, provider=provider)
        status = _validate_runtime(
            provider,
            runtime,
            database_only=True,
            connection_id=connection_id or None,
            display_name=display_name,
        )
        _store_cache(status, cache_key=cache_key)
        statuses.append(status)
    return statuses


def _validate_all_registered_providers(
    *,
    force_refresh: bool = False,
) -> list[MCPConnectionStatus]:
    """Validate every registered provider using environment credentials (script fallback)."""
    sources = registered_sources()
    cache_scope = "env"
    if not force_refresh and _is_cache_valid() and all(
        f"{cache_scope}:{source}" in _cache for source in sources
    ):
        return [_cache[f"{cache_scope}:{source}"] for source in sources]

    statuses: list[MCPConnectionStatus] = []
    for source in sources:
        cache_key = f"{cache_scope}:{source}"
        status = _validate_runtime(source, None, database_only=False)
        _store_cache(status, cache_key=cache_key)
        statuses.append(status)
    return statuses


def validate_connection_by_id(
    connection_id: str,
    *,
    workspace_id: str,
    force_refresh: bool = False,
) -> MCPConnectionStatus:
    """Validate one workspace integration connection by database id."""
    from integrations.connection_repository import get_connection

    cid = (connection_id or "").strip()
    ws = workspace_id.strip()
    if not cid or not ws:
        raise ValueError("connection_id and workspace_id are required")

    with get_db_session_readonly() as session:
        row = get_connection(session, cid)
        if row is not None:
            session.expunge(row)
    if row is None or str(row.workspace_id) != ws or not bool(row.is_enabled):
        return MCPConnectionStatus(
            provider="jira",  # placeholder; overwritten below when possible
            configured=False,
            healthy=False,
            last_checked=_utc_now_iso(),
            error_message="integration connection not found",
            connection_id=cid,
        )

    provider_raw = str(getattr(row, "provider", "") or "").strip().lower()
    if provider_raw not in registered_sources():
        return MCPConnectionStatus(
            provider="jira",
            configured=False,
            healthy=False,
            last_checked=_utc_now_iso(),
            error_message=f"unsupported provider: {provider_raw}",
            connection_id=cid,
            display_name=str(getattr(row, "display_name", "") or "") or None,
        )
    provider = provider_raw  # type: ignore[assignment]
    display_name = str(getattr(row, "display_name", "") or "") or None
    cache_key = _cache_key(workspace_id=ws, provider=provider, connection_id=cid)
    if not force_refresh and _is_cache_valid() and cache_key in _cache:
        return _cache[cache_key]

    runtime = runtime_connection_from_row(row, provider=provider)
    status = _validate_runtime(
        provider,
        runtime,
        database_only=True,
        connection_id=cid,
        display_name=display_name,
    )
    _store_cache(status, cache_key=cache_key)
    return status


def validate_provider(
    provider_name: str,
    *,
    workspace_id: str | None = None,
    force_refresh: bool = False,
) -> MCPConnectionStatus:
    """Validate one MCP provider connection."""
    name = _normalize_provider(provider_name)
    ws = (workspace_id or "").strip()

    if ws:
        runtime = resolve_runtime_connection_for_workspace(ws, name, repo_name=None)
        if runtime is None:
            return MCPConnectionStatus(
                provider=name,
                configured=False,
                healthy=False,
                last_checked=_utc_now_iso(),
                error_message="no integration connection configured",
            )
        cache_key = _cache_key(
            workspace_id=ws,
            provider=name,
            connection_id=runtime.connection_id or None,
        )
        if not force_refresh and _is_cache_valid() and cache_key in _cache:
            return _cache[cache_key]
        status = _validate_runtime(
            name,
            runtime,
            database_only=True,
            connection_id=runtime.connection_id or None,
            display_name=None,
        )
        _store_cache(status, cache_key=cache_key)
        return status

    cache_key = _cache_key(workspace_id=None, provider=name)
    if not force_refresh and _is_cache_valid() and cache_key in _cache:
        return _cache[cache_key]

    status = _validate_runtime(name, None, database_only=False)
    _store_cache(status, cache_key=cache_key)
    return status


def validate_all_connections(
    *,
    workspace_id: str | None = None,
    force_refresh: bool = False,
) -> list[MCPConnectionStatus]:
    """Validate MCP connections for a workspace or all env-backed providers."""
    ws = (workspace_id or "").strip()
    if ws:
        return _validate_workspace_connections(ws, force_refresh=force_refresh)
    return _validate_all_registered_providers(force_refresh=force_refresh)
