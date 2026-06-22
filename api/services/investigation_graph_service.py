"""API service for investigation graph visualization and similarity search."""

from __future__ import annotations

from typing import Any

from graph.graph_visualization_service import get_investigation_graph, investigation_exists
from graph.neo4j_client import Neo4jClient
from graph.retrieval_models import SimilarInvestigation
from graph.similar_incident_service import find_similar_investigations


class InvestigationGraphNotFoundError(Exception):
    """Raised when the investigation graph root node is missing in Neo4j."""


def _get_neo4j_client() -> Neo4jClient:
    return Neo4jClient.from_env()


def fetch_investigation_graph(
    investigation_id: str,
    *,
    depth: int | None = None,
    graph_client: Neo4jClient | None = None,
) -> dict[str, Any]:
    """Load visualization graph for an investigation id."""
    client = graph_client or _get_neo4j_client()
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()

    try:
        if not investigation_exists(client, investigation_id):
            raise InvestigationGraphNotFoundError(f"investigation not found: {investigation_id}")
        return get_investigation_graph(client, investigation_id, depth=depth)
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()


def fetch_similar_investigations(
    investigation_id: str,
    *,
    limit: int | None = None,
    graph_client: Neo4jClient | None = None,
) -> list[SimilarInvestigation]:
    """Find investigations similar to the given investigation id."""
    client = graph_client or _get_neo4j_client()
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()

    try:
        if not investigation_exists(client, investigation_id):
            raise InvestigationGraphNotFoundError(f"investigation not found: {investigation_id}")
        return find_similar_investigations(client, investigation_id, limit=limit)
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()
