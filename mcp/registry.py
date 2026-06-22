"""MCP provider registry."""

from __future__ import annotations

from typing import Dict, Type

from mcp.providers.base import BaseMCPProvider
from mcp.providers.datadog_provider import DatadogProvider
from mcp.providers.github_provider import GitHubProvider
from mcp.providers.gitlab_provider import GitLabProvider
from mcp.providers.jenkins_provider import JenkinsProvider
from mcp.providers.jira_provider import JiraProvider
from mcp.providers.kubernetes_provider import KubernetesProvider
from mcp.providers.pagerduty_provider import PagerDutyProvider
from mcp.schemas.common import MCPSourceName

_PROVIDERS: Dict[MCPSourceName, Type[BaseMCPProvider]] = {
    "jira": JiraProvider,
    "github": GitHubProvider,
    "gitlab": GitLabProvider,
    "jenkins": JenkinsProvider,
    "datadog": DatadogProvider,
    "kubernetes": KubernetesProvider,
    "pagerduty": PagerDutyProvider,
}


def get_provider_class(source: MCPSourceName) -> Type[BaseMCPProvider]:
    if source not in _PROVIDERS:
        raise KeyError(f"unknown MCP source: {source}")
    return _PROVIDERS[source]


def registered_sources() -> list[MCPSourceName]:
    return list(_PROVIDERS.keys())
