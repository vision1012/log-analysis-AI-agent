"""
Status transition logic for RCA_ATTRIBUTED edges.

Locked rules:
- confirm: selected -> accepted, all others -> rejected (max one accepted per anomaly)
- reject: only that candidate -> rejected
- reject_all: all candidates -> rejected
- rollback: accepted -> rejected
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from graph.neo4j_client import Neo4jClient
from graph.writer import GraphWriter


def _get_client() -> Neo4jClient:
    return Neo4jClient.from_env()


def _get_writer(client: Optional[Neo4jClient] = None) -> GraphWriter:
    c = client or _get_client()
    if not getattr(c, "_driver", None):
        c.connect()
    return GraphWriter(c)


def confirm_candidate(
    anomaly_id: str,
    file_id: str,
    run_id: str,
    *,
    actor_id: str,
    reason: str = "",
    graph_client: Optional[Neo4jClient] = None,
    graph_writer: Optional[GraphWriter] = None,
) -> None:
    """
    Confirm candidate: selected becomes accepted, all others for anomaly become rejected.
    Max one accepted per anomaly.
    """
    client = graph_client or _get_client()
    writer = graph_writer or _get_writer(client)
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()

    act, ts, r = actor_id, datetime.now(timezone.utc).isoformat(), reason
    batch: list[tuple[str, dict]] = []
    writer.reject_other_candidates_for_anomaly(
        anomaly_id, file_id, run_id,
        actor_id=act, timestamp=ts, reason=r,
        _batch=batch,
    )
    writer.update_rca_attributed_status(
        anomaly_id, file_id, run_id, "accepted",
        actor_id=act, timestamp=ts, reason=r,
        _batch=batch,
    )
    writer.write_atomic(batch)

    if own_client and getattr(client, "_driver", None):
        client.close()


def reject_candidate(
    anomaly_id: str,
    file_id: str,
    run_id: str,
    *,
    actor_id: str,
    reason: str = "",
    graph_client: Optional[Neo4jClient] = None,
    graph_writer: Optional[GraphWriter] = None,
) -> None:
    """Reject only that candidate."""
    client = graph_client or _get_client()
    writer = graph_writer or _get_writer(client)
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        writer.update_rca_attributed_status(
            anomaly_id, file_id, run_id, "rejected",
            actor_id=actor_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()


def reject_all(
    anomaly_id: str,
    *,
    actor_id: str,
    reason: str = "",
    graph_client: Optional[Neo4jClient] = None,
    graph_writer: Optional[GraphWriter] = None,
) -> None:
    """Reject all candidates for anomaly."""
    client = graph_client or _get_client()
    writer = graph_writer or _get_writer(client)
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        writer.reject_all_candidates_for_anomaly(
            anomaly_id,
            actor_id=actor_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()


def rollback(
    anomaly_id: str,
    *,
    actor_id: str,
    reason: str = "",
    graph_client: Optional[Neo4jClient] = None,
    graph_writer: Optional[GraphWriter] = None,
) -> None:
    """Rollback: accepted -> rejected."""
    client = graph_client or _get_client()
    writer = graph_writer or _get_writer(client)
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        writer.rollback_accepted_to_rejected(
            anomaly_id,
            actor_id=actor_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()
