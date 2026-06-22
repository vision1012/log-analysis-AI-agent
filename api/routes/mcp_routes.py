"""MCP API routes."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps.auth import get_current_user
from mcp.config import MCPFetchParams, default_enabled_sources, mcp_enabled
from mcp.connection_manager import validate_all_connections, validate_provider
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
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    enabled_sources: Optional[List[MCPSourceName]] = None


class MCPConnectionsResponse(BaseModel):
    connections: List[MCPConnectionStatus]


@router.get("/mcp/connections", response_model=MCPConnectionsResponse)
async def list_mcp_connections(_user: UserResponse = Depends(get_current_user)) -> MCPConnectionsResponse:
    """Return cached MCP connection status for all providers."""
    return MCPConnectionsResponse(connections=validate_all_connections())


@router.post("/mcp/connections/validate", response_model=MCPConnectionsResponse)
async def validate_mcp_connections(_user: UserResponse = Depends(get_current_user)) -> MCPConnectionsResponse:
    """Force-refresh MCP connection health for all providers."""
    return MCPConnectionsResponse(connections=validate_all_connections(force_refresh=True))


@router.post("/mcp/connections/{provider}/validate", response_model=MCPConnectionStatus)
async def validate_mcp_provider_connection(
    provider: str,
    _user: UserResponse = Depends(get_current_user),
) -> MCPConnectionStatus:
    """Force-refresh MCP connection health for one provider."""
    return validate_provider(provider, force_refresh=True)


@router.get("/mcp/status", response_model=MCPStatusResponse)
async def mcp_status(_user: UserResponse = Depends(get_current_user)) -> MCPStatusResponse:
    """Return MCP feature flag and per-provider health."""
    orchestrator = MCPOrchestrator()
    return MCPStatusResponse(
        mcp_enabled=mcp_enabled(),
        providers=orchestrator.health_status(),
    )


@router.post("/mcp/context/preview")
async def mcp_context_preview(
    body: MCPContextPreviewRequest,
    _user: UserResponse = Depends(get_current_user),
) -> dict:
    """Preview unified investigation context without running RCA."""
    orchestrator = MCPOrchestrator()
    params = MCPFetchParams(
        ticket_key=body.ticket_key,
        service_name=body.service_name,
        repo_name=body.repo_name,
        start_time=body.start_time,
        end_time=body.end_time,
        enabled_sources=body.enabled_sources or default_enabled_sources(),
    )
    context = orchestrator.fetch_context(params)
    return context.model_dump()
