"""Runtime provider connection resolved from Postgres or environment fallback."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ConnectionSource = Literal["database", "env"]


class ProviderRuntimeConnection(BaseModel):
    """Decrypted integration connection passed to MCP providers at fetch time."""

    connection_id: str = ""
    workspace_id: str = ""
    provider: str
    base_url: str | None = None
    org_name: str | None = None
    project_key: str | None = None
    repo_name: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)
    source: ConnectionSource = "database"
