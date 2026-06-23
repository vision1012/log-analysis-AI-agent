"""API layer for investigation replay mode."""

from __future__ import annotations

from api.services.investigation_graph_service import InvestigationGraphNotFoundError
from graph.graph_visualization_service import investigation_exists
from graph.neo4j_client import Neo4jClient
from replay.replay_models import InvestigationReplay
from replay.replay_service import build_replay


def _get_client() -> Neo4jClient:
    return Neo4jClient.from_env()


def fetch_investigation_replay(
    investigation_id: str,
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    event_type: str | None = None,
    playback_speed: float | None = None,
) -> InvestigationReplay:
    """Build and return ordered replay frames for an investigation."""
    client = _get_client()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        if not investigation_exists(client, investigation_id):
            raise InvestigationGraphNotFoundError(f"investigation not found: {investigation_id}")
        return build_replay(
            client,
            investigation_id,
            from_ts=from_ts,
            to_ts=to_ts,
            event_type=event_type,
            playback_speed=playback_speed,
        )
    finally:
        if getattr(client, "_driver", None):
            client.close()
