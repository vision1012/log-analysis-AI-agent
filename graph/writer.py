"""
Graph writer for RCA entities and edges.

Writes Anomaly, StackFrame, File, Commit, Deployment nodes and relationships.
"""

from __future__ import annotations

from typing import Any, Optional

# from graph.neo4j_client import Neo4jClient


class GraphWriter:
    """Writes nodes and edges to Neo4j. Per-anomaly atomic writes for RCA_ATTRIBUTED."""

    def __init__(self, client: Any) -> None:
        """
        Initialize writer.

        Args:
            client: Neo4jClient instance.
        """
        self._client = client

    def write_anomaly(self, anomaly_id: str, trace_ref: str, timestamp: str, **props: Any) -> None:
        """Upsert Anomaly node."""
        pass

    def write_stack_frame(
        self,
        frame_id: str,
        trace_ref: str,
        symbol_name: str,
        frame_order: int,
        resolution: str = "resolved",
        **props: Any,
    ) -> None:
        """Upsert StackFrame node."""
        pass

    def write_has_frame(self, anomaly_id: str, frame_id: str, frame_order: int) -> None:
        """Create HAS_FRAME edge."""
        pass

    def write_in_file(self, frame_id: str, file_id: str) -> None:
        """Create IN_FILE edge."""
        pass

    def write_rca_attributed(
        self,
        anomaly_id: str,
        frame_id: str,
        run_id: str,
        method: str,
        confidence: float,
        status: str,
        evidence_ref: str,
        attributed_at: str,
    ) -> None:
        """Create RCA_ATTRIBUTED edge. Use within per-anomaly atomic transaction."""
        pass

    def supersede_prior_attributions(self, anomaly_id: str, run_id: str) -> None:
        """Set prior candidate/accepted to superseded before writing new attributions."""
        pass
