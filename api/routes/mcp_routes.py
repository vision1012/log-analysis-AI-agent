"""MCP API routes."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.deps.auth import get_current_user
from integrations.connection_service import assert_workspace_access
from mcp.config import MCPFetchParams, default_enabled_sources, mcp_enabled
from mcp.connection_manager import (
    validate_all_connections,
    validate_connection_by_id,
    validate_provider,
)
from mcp.connection_models import MCPConnectionStatus
from mcp.orchestrator import MCPOrchestrator
from mcp.schemas.common import MCPSourceName, ProviderHealth
from schemas.users import UserResponse

router = APIRouter(dependencies=[Depends(get_current_user)])


class MCPStatusResponse(BaseModel):
    mcp_enabled: bool
    providers: List[ProviderHealth]


class MCPContextPreviewRequest(BaseModel):
    ticket_key: str = Field(..., min_length=1)
    service_name: str = ""
    repo_name: str = ""
    workspace_id: str = ""
    provider_connection_ids: dict[str, str] = Field(default_factory=dict)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    enabled_sources: Optional[List[MCPSourceName]] = None


class MCPConnectionsResponse(BaseModel):
    connections: List[MCPConnectionStatus]


def _resolve_workspace_id(user: UserResponse, workspace_id: str | None) -> str:
    ws = (workspace_id or user.team or user.user_id or "").strip()
    if not ws:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "workspace_required", "message": "workspace_id is required"},
        )
    assert_workspace_access(user, ws)
    return ws


@router.get("/mcp/connections", response_model=MCPConnectionsResponse)
async def list_mcp_connections(
    workspace_id: Optional[str] = Query(None),
    current_user: UserResponse = Depends(get_current_user),
) -> MCPConnectionsResponse:
    """Return MCP connection status for enabled workspace integration connections."""
    ws = _resolve_workspace_id(current_user, workspace_id)
    return MCPConnectionsResponse(connections=validate_all_connections(workspace_id=ws))


@router.post("/mcp/connections/validate", response_model=MCPConnectionsResponse)
async def validate_mcp_connections(
    workspace_id: Optional[str] = Query(None),
    current_user: UserResponse = Depends(get_current_user),
) -> MCPConnectionsResponse:
    """Force-refresh MCP connection health for all enabled workspace connections."""
    ws = _resolve_workspace_id(current_user, workspace_id)
    return MCPConnectionsResponse(
        connections=validate_all_connections(workspace_id=ws, force_refresh=True)
    )


@router.post("/mcp/connections/validate-all", response_model=MCPConnectionsResponse)
async def validate_all_mcp_connections(
    workspace_id: Optional[str] = Query(None),
    current_user: UserResponse = Depends(get_current_user),
) -> MCPConnectionsResponse:
    """Alias for validate — validates all enabled workspace integration connections."""
    ws = _resolve_workspace_id(current_user, workspace_id)
    return MCPConnectionsResponse(
        connections=validate_all_connections(workspace_id=ws, force_refresh=True)
    )


@router.post("/mcp/connections/by-id/{connection_id}/validate", response_model=MCPConnectionStatus)
async def validate_mcp_connection_by_id(
    connection_id: str,
    workspace_id: Optional[str] = Query(None),
    current_user: UserResponse = Depends(get_current_user),
) -> MCPConnectionStatus:
    """Force-refresh MCP health for one integration_connections row."""
    ws = _resolve_workspace_id(current_user, workspace_id)
    return validate_connection_by_id(connection_id, workspace_id=ws, force_refresh=True)


@router.post("/mcp/connections/{provider}/validate", response_model=MCPConnectionStatus)
async def validate_mcp_provider_connection(
    provider: str,
    workspace_id: Optional[str] = Query(None),
    current_user: UserResponse = Depends(get_current_user),
) -> MCPConnectionStatus:
    """Force-refresh MCP connection health for one workspace provider."""
    ws = _resolve_workspace_id(current_user, workspace_id)
    return validate_provider(provider, workspace_id=ws, force_refresh=True)


@router.get("/mcp/status", response_model=MCPStatusResponse)
async def mcp_status(
    workspace_id: Optional[str] = Query(None),
    current_user: UserResponse = Depends(get_current_user),
) -> MCPStatusResponse:
    """Return MCP feature flag and per-provider health from workspace connections."""
    ws = _resolve_workspace_id(current_user, workspace_id)
    orchestrator = MCPOrchestrator()
    return MCPStatusResponse(
        mcp_enabled=mcp_enabled(),
        providers=orchestrator.health_status(workspace_id=ws),
    )


@router.post("/mcp/context/preview")
async def mcp_context_preview(
    body: MCPContextPreviewRequest,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """Preview unified investigation context without running RCA."""
    ws = (body.workspace_id or current_user.team or current_user.user_id or "").strip()
    if ws:
        assert_workspace_access(current_user, ws)
    orchestrator = MCPOrchestrator()
    params = MCPFetchParams(
        ticket_key=body.ticket_key,
        service_name=body.service_name,
        repo_name=body.repo_name,
        workspace_id=ws,
        provider_connection_ids=dict(body.provider_connection_ids or {}),
        start_time=body.start_time,
        end_time=body.end_time,
        enabled_sources=body.enabled_sources or default_enabled_sources(),
    )
    context = orchestrator.fetch_context(params)
    return context.model_dump()
