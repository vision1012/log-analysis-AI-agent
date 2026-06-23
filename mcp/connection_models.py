"""MCP connection management models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from mcp.schemas.common import MCPSourceName


class MCPConnectionStatus(BaseModel):
    """Centralized MCP provider connection status."""

    provider: MCPSourceName
    configured: bool
    healthy: bool
    last_checked: str
    error_message: Optional[str] = None
