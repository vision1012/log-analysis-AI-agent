"""Persist unified MCP investigation context into Neo4j."""

from __future__ import annotations

import logging
import os
from typing import Optional

from graph.investigation_writer import InvestigationGraphWriter
from graph.neo4j_client import Neo4jClient
from mcp.context.investigation_context import UnifiedInvestigationContext

logger = logging.getLogger(__name__)


def investigation_graph_enabled() -> bool:
    """Whether MCP investigation graph persistence is enabled."""
    raw = (os.environ.get("INVESTIGATION_GRAPH_ENABLED") or "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class InvestigationGraphService:
    """Write MCP investigation context to Neo4j without affecting RCA ranking."""

    def __init__(self, client: Optional[Neo4jClient] = None) -> None:
        self._client = client
        self._owns_client = client is None

    def persist_investigation_context(
        self,
        investigation_id: str,
        context: UnifiedInvestigationContext,
        *,
        ticket_key: str = "",
    ) -> dict[str, int]:
        """
        Persist normalized MCP entities and investigation chain relationships.

        Returns write counts. Raises on Neo4j failure — callers should catch.
        """
        client = self._client or Neo4jClient.from_env()
        created_client = self._client is None
        if created_client:
            client.connect()
        try:
            writer = InvestigationGraphWriter(client)
            key = ticket_key
            if not key and context.ticket_context:
                key = context.ticket_context.issue_key
            return writer.write_investigation_context(
                investigation_id,
                context,
                ticket_key=key,
            )
        finally:
            if created_client:
                client.close()


def persist_investigation_context_safe(
    investigation_id: str,
    context: UnifiedInvestigationContext,
    *,
    ticket_key: str = "",
) -> bool:
    """
    Best-effort graph persistence. Never raises — RCA must continue on failure.
    """
    if not investigation_graph_enabled():
        return False
    if context_is_empty(context):
        return False
    try:
        InvestigationGraphService().persist_investigation_context(
            investigation_id,
            context,
            ticket_key=ticket_key,
        )
        return True
    except Exception as exc:
        logger.warning(
            "investigation_graph.persist_failed investigation_id=%s err=%s",
            investigation_id,
            exc,
        )
        return False


def context_is_empty(context: UnifiedInvestigationContext) -> bool:
    """Return True when there is nothing meaningful to persist."""
    return not any(
        [
            context.ticket_context,
            context.commits,
            context.pull_requests,
            context.merge_requests,
            context.build_events,
            context.deployment_events,
            context.metric_events,
            context.alert_events,
            context.trace_events,
            context.pod_events,
            context.container_events,
            context.node_events,
            context.pagerduty_incidents,
            context.runbook_documents,
            context.known_issue_documents,
            context.architecture_documents,
        ]
    )
