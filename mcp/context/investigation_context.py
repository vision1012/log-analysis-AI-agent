"""Unified investigation context returned by MCP orchestration."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from mcp.schemas.common import SourceMetadata
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.gitlab_models import McpDeploymentEvent, McpGitLabCommit, McpMergeRequest, McpPipeline
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.jira_models import McpTicketContext


class UnifiedInvestigationContext(BaseModel):
    """
    Provider-agnostic investigation context for signal enrichment.

    No raw provider payloads are exposed — only normalized objects.
    """

    ticket_context: Optional[McpTicketContext] = None
    commits: List[McpCommit | McpGitLabCommit] = Field(default_factory=list)
    pull_requests: List[McpPullRequest] = Field(default_factory=list)
    merge_requests: List[McpMergeRequest] = Field(default_factory=list)
    build_events: List[BuildEvent] = Field(default_factory=list)
    deployment_events: List[DeploymentEvent | McpDeploymentEvent] = Field(default_factory=list)
    pipelines: List[McpPipeline] = Field(default_factory=list)
    source_metadata: List[SourceMetadata] = Field(default_factory=list)
