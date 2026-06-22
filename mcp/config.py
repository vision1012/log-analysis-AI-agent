"""MCP feature flags and fetch parameters."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from mcp.schemas.common import MCPSourceName


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def mcp_enabled() -> bool:
    return _env_bool("MCP_ENABLED", default=False)


def jira_mcp_enabled() -> bool:
    return mcp_enabled() and _env_bool("JIRA_MCP_ENABLED", default=True)


def github_mcp_enabled() -> bool:
    return mcp_enabled() and _env_bool("GITHUB_MCP_ENABLED", default=True)


def gitlab_mcp_enabled() -> bool:
    return mcp_enabled() and _env_bool("GITLAB_MCP_ENABLED", default=True)


def jenkins_mcp_enabled() -> bool:
    return mcp_enabled() and _env_bool("JENKINS_MCP_ENABLED", default=False)


def datadog_mcp_enabled() -> bool:
    return mcp_enabled() and _env_bool("DATADOG_MCP_ENABLED", default=False)


def kubernetes_mcp_enabled() -> bool:
    return mcp_enabled() and _env_bool("KUBERNETES_MCP_ENABLED", default=False)


def default_enabled_sources() -> List[MCPSourceName]:
    sources: List[MCPSourceName] = []
    if jira_mcp_enabled():
        sources.append("jira")
    if github_mcp_enabled():
        sources.append("github")
    if gitlab_mcp_enabled():
        sources.append("gitlab")
    if jenkins_mcp_enabled():
        sources.append("jenkins")
    if datadog_mcp_enabled():
        sources.append("datadog")
    if kubernetes_mcp_enabled():
        sources.append("kubernetes")
    return sources


@dataclass(frozen=True)
class MCPFetchParams:
    ticket_key: str
    service_name: str = ""
    repo_name: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    enabled_sources: List[MCPSourceName] = field(default_factory=default_enabled_sources)

    def resolved_repo_name(self) -> str:
        explicit = (self.repo_name or "").strip()
        if explicit:
            return explicit
        return (os.environ.get("MCP_DEFAULT_REPO") or "").strip()

    def resolved_gitlab_project(self) -> str:
        explicit = (os.environ.get("GITLAB_PROJECT_ID") or "").strip()
        if explicit:
            return explicit
        repo = self.resolved_repo_name()
        return repo.replace("/", "%2F") if "/" in repo else repo
