"""Shared MCP schema types."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

MCPSourceName = Literal["jira", "github", "gitlab", "jenkins"]
MetadataSourceName = Literal["jira", "github", "gitlab", "jenkins", "correlator"]


class InvestigationCorrelation(BaseModel):
    """Normalized link between investigation artifacts (stored in source_metadata)."""

    relation: Literal["commit_to_build", "build_to_deployment", "pr_to_commit"]
    from_ref: str
    to_ref: str
    commit_sha: str = ""
    build_number: Optional[int] = None
    deployment_id: str = ""
    environment: str = ""
    pr_number: Optional[int] = None


class SourceMetadata(BaseModel):
    """Provenance for a normalized MCP payload slice."""

    source: MetadataSourceName
    fetched_at: datetime
    ok: bool = True
    detail: str = ""
    correlations: List[InvestigationCorrelation] = Field(default_factory=list)


class ProviderHealth(BaseModel):
    """Health probe result for one MCP provider."""

    source: MCPSourceName
    enabled: bool
    configured: bool
    reachable: bool
    detail: str = ""
