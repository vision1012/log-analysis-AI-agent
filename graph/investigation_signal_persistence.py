"""Persist MCP Signal Engine v2 contributions to Neo4j."""

from __future__ import annotations

import logging
from typing import Any

from graph.investigation_writer import InvestigationGraphWriter
from graph.neo4j_client import Neo4jClient
from rca_engine.mcp_signal_v2_config import MCP_SIGNAL_V2_NAMES

logger = logging.getLogger(__name__)


def persist_investigation_v2_signals(
    investigation_id: str,
    *,
    candidate_path: str,
    contributions_payload: dict[str, Any],
) -> int:
    """
    Write InvestigationSignal nodes for MCP v2 contributions.

    Returns number of signals persisted.
    """
    block = contributions_payload.get("mcp_signal_engine_v2")
    if not isinstance(block, dict):
        return 0
    signals = block.get("signals")
    if not isinstance(signals, list):
        return 0

    client = Neo4jClient.from_env()
    client.connect()
    try:
        writer = InvestigationGraphWriter(client)
        batch: list[tuple[str, dict[str, Any]]] = []
        count = 0
        for entry in signals:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "")
            if name not in MCP_SIGNAL_V2_NAMES:
                continue
            writer.upsert_investigation_signal(
                investigation_id,
                signal_name=name,
                candidate_path=candidate_path or str(block.get("candidate_path") or ""),
                value=float(entry.get("value") or 0),
                weight=float(entry.get("weight") or 0),
                contribution=float(entry.get("contribution") or 0),
                evidence=dict(entry.get("evidence") or {}),
                _batch=batch,
            )
            count += 1
        if batch:
            writer.write_atomic(batch)
        return count
    finally:
        client.close()


def persist_investigation_v2_signals_safe(
    investigation_id: str,
    *,
    candidate_path: str,
    contributions_payload: dict[str, Any] | None,
) -> bool:
    """Best-effort v2 signal persistence; never raises."""
    if not investigation_id or not contributions_payload:
        return False
    try:
        count = persist_investigation_v2_signals(
            investigation_id,
            candidate_path=candidate_path,
            contributions_payload=contributions_payload,
        )
        return count > 0
    except Exception as exc:
        logger.warning(
            "investigation_graph.v2_signals_failed investigation_id=%s err=%s",
            investigation_id,
            exc,
        )
        return False
