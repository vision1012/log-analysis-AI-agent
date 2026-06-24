"""Resolve workspace integration connections for MCP providers."""

from __future__ import annotations

import logging
from typing import Mapping

from db.postgres.connection import get_db_session_readonly
from integrations.connection_repository import get_connection, get_enabled_connection
from integrations.credential_encryption import decrypt_credentials
from mcp.config import MCPFetchParams
from mcp.runtime_connection import ProviderRuntimeConnection
from mcp.schemas.common import MCPSourceName

logger = logging.getLogger(__name__)


def runtime_connection_from_row(row: object, *, provider: str) -> ProviderRuntimeConnection:
    """Build a decrypted runtime connection from an integration_connections row."""
    return _row_to_runtime(row, provider=provider)


def _row_to_runtime(row: object, *, provider: str) -> ProviderRuntimeConnection:
    credentials = decrypt_credentials(getattr(row, "encrypted_credentials"))
    return ProviderRuntimeConnection(
        connection_id=str(getattr(row, "id")),
        workspace_id=str(getattr(row, "workspace_id")),
        provider=provider,
        base_url=getattr(row, "base_url", None),
        org_name=getattr(row, "org_name", None),
        project_key=getattr(row, "project_key", None),
        repo_name=getattr(row, "repo_name", None),
        config_json=dict(getattr(row, "config_json") or {}),
        credentials=credentials,
        source="database",
    )


def resolve_runtime_connection_for_workspace(
    workspace_id: str,
    provider: MCPSourceName,
    *,
    repo_name: str | None = None,
    connection_id: str | None = None,
) -> ProviderRuntimeConnection | None:
    """Load and decrypt an enabled integration connection for a workspace provider."""
    ws = (workspace_id or "").strip()
    if not ws:
        return None

    try:
        with get_db_session_readonly() as session:
            row = None
            if connection_id:
                row = get_connection(session, connection_id.strip())
                if row is not None and (
                    row.workspace_id != ws
                    or row.provider != provider
                    or not row.is_enabled
                ):
                    row = None
            if row is None:
                row = get_enabled_connection(
                    session,
                    workspace_id=ws,
                    provider=provider,
                    repo_name=repo_name,
                )
            if row is None:
                return None
            return _row_to_runtime(row, provider=provider)
    except Exception as exc:
        logger.warning(
            "mcp.integration_resolver.failed workspace_id=%s provider=%s err=%s",
            ws,
            provider,
            exc,
        )
        return None


def resolve_runtime_connection(
    params: MCPFetchParams,
    provider: MCPSourceName,
) -> ProviderRuntimeConnection | None:
    """Resolve runtime connection for orchestrator fetch using MCP params."""
    ws = (params.workspace_id or "").strip()
    if not ws:
        return None
    overrides: Mapping[str, str] = params.provider_connection_ids or {}
    connection_id = (overrides.get(provider) or "").strip() or None
    repo_name = (params.repo_name or "").strip() or None
    return resolve_runtime_connection_for_workspace(
        ws,
        provider,
        repo_name=repo_name,
        connection_id=connection_id,
    )
