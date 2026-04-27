"""
Read helpers for ``Anomaly`` nodes (Neo4j).
"""

from __future__ import annotations

from typing import Any, Optional

from neo4j import Driver

from db.neo4j.connection import get_driver


def _to_plain(value: Any) -> Any:
    """Normalize Neo4j temporal types for plain dict responses."""
    if value is None:
        return None
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        return to_native()
    return value


def _node_to_dict(node: Any) -> dict[str, Any]:
    return {key: _to_plain(node[key]) for key in node.keys()}


def list_anomalies(
    *,
    limit: int = 50,
    offset: int = 0,
    driver: Optional[Driver] = None,
) -> list[dict[str, Any]]:
    """
    Return anomaly nodes ordered by newest timestamp first.
    """
    drv = driver or get_driver()
    query = """
    MATCH (a:Anomaly)
    RETURN a
    ORDER BY a.timestamp DESC, a.id ASC
    SKIP $offset
    LIMIT $limit
    """
    with drv.session() as session:
        result = session.run(query, {"limit": limit, "offset": offset})
        return [_node_to_dict(record["a"]) for record in result]
