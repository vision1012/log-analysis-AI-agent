"""
Deterministic RCA runner. Delegates to rca_runner.run_deterministic_rca.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from rca_engine.rca_runner import RCARunResult, run_deterministic_rca as _run_deterministic_rca

if TYPE_CHECKING:
    from graph.neo4j_client import Neo4jClient
    from graph.writer import GraphWriter
    from artifacts.evidence_store import EvidenceStore


def run_deterministic_rca(
    anomaly_id: str,
    trigger_type: str,
    *,
    graph_client: "Neo4jClient",
    graph_writer: "GraphWriter",
    evidence_store: "EvidenceStore",
    run_id: Optional[str] = None,
    override: bool = False,
    **kwargs: Any,
) -> Optional[RCARunResult]:
    """
    Execute deterministic RCA for one anomaly.

    Delegates to rca_runner.run_deterministic_rca.
    """
    return _run_deterministic_rca(
        anomaly_id,
        trigger_type,
        graph_client=graph_client,
        graph_writer=graph_writer,
        evidence_store=evidence_store,
        run_id=run_id,
        override=override,
        **kwargs,
    )
