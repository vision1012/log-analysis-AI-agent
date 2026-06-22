"""MCP orchestrator: aggregate normalized context from enabled providers."""

from __future__ import annotations

import logging

from mcp.config import MCPFetchParams, mcp_enabled
from mcp.context.build_commit_correlator import correlate_and_attach_metadata
from mcp.context.deployment_observability_correlator import (
    correlate_deployment_observability_and_attach_metadata,
)
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.registry import get_provider_class, registered_sources
from mcp.schemas.common import ProviderHealth

logger = logging.getLogger(__name__)


class MCPOrchestrator:
    """
    Fetch external investigation context from JIRA, GitHub, GitLab, Jenkins, and Datadog.

    Each provider returns normalized slices; the orchestrator merges them into
    :class:`UnifiedInvestigationContext`. Provider failures are logged and skipped
    so the RCA pipeline can continue with partial context.
    """

    def fetch_context(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        if not mcp_enabled():
            return UnifiedInvestigationContext()

        context = UnifiedInvestigationContext()
        for source in params.enabled_sources:
            if source not in registered_sources():
                logger.warning("mcp.orchestrator.skip unknown source=%s", source)
                continue
            provider_cls = get_provider_class(source)
            provider = provider_cls()
            if not provider.is_enabled():
                continue
            try:
                partial = provider.fetch(params)
                context = _merge_unified(context, partial)
            except Exception as exc:
                logger.warning("mcp.orchestrator.provider_failed source=%s err=%s", source, exc)
        return correlate_deployment_observability_and_attach_metadata(
            correlate_and_attach_metadata(context)
        )

    def health_status(self) -> list[ProviderHealth]:
        if not mcp_enabled():
            return [
                ProviderHealth(
                    source=src,
                    enabled=False,
                    configured=False,
                    reachable=False,
                    detail="MCP_ENABLED=false",
                )
                for src in registered_sources()
            ]
        out: list[ProviderHealth] = []
        for source in registered_sources():
            provider = get_provider_class(source)()
            out.append(provider.health_check())
        return out


def _merge_unified(
    left: UnifiedInvestigationContext,
    right: UnifiedInvestigationContext,
) -> UnifiedInvestigationContext:
    data = left.model_dump()
    r = right.model_dump()
    if r.get("ticket_context") and not data.get("ticket_context"):
        data["ticket_context"] = r["ticket_context"]
    data["commits"] = list(data.get("commits") or []) + list(r.get("commits") or [])
    data["pull_requests"] = list(data.get("pull_requests") or []) + list(r.get("pull_requests") or [])
    data["merge_requests"] = list(data.get("merge_requests") or []) + list(r.get("merge_requests") or [])
    data["build_events"] = list(data.get("build_events") or []) + list(r.get("build_events") or [])
    data["deployment_events"] = list(data.get("deployment_events") or []) + list(r.get("deployment_events") or [])
    data["metric_events"] = list(data.get("metric_events") or []) + list(r.get("metric_events") or [])
    data["alert_events"] = list(data.get("alert_events") or []) + list(r.get("alert_events") or [])
    data["trace_events"] = list(data.get("trace_events") or []) + list(r.get("trace_events") or [])
    data["service_health_events"] = list(data.get("service_health_events") or []) + list(
        r.get("service_health_events") or []
    )
    data["pipelines"] = list(data.get("pipelines") or []) + list(r.get("pipelines") or [])
    data["source_metadata"] = list(data.get("source_metadata") or []) + list(r.get("source_metadata") or [])
    return UnifiedInvestigationContext.model_validate(data)
