"""
Deterministic RCA runner (stub).

Implements N_candidates=3, K_frames=5. See deterministic_rca_v1.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# from graph.neo4j_client import Neo4jClient
# from graph.writer import GraphWriter
# from gates.pre_rca_gate import run_pre_rca_gate
# from artifacts.evidence_store import EvidenceStore


@dataclass
class RCARunResult:
    """Result of an RCA run."""

    run_id: str
    anomaly_id: str
    attribution_count: int
    bundle_ids: list[str]


def run_deterministic_rca(
    anomaly_id: str,
    run_id: str,
    *,
    graph_client: Any = None,
    graph_writer: Any = None,
    evidence_store: Any = None,
    trigger: str = "auto",
    override: bool = False,
) -> Optional[RCARunResult]:
    """
    Execute deterministic RCA for one anomaly.

    Pre-RCA gate → candidate generation (K_frames=5) → signals → rank → top N_candidates=3
    → Post-RCA gate → create bundles → persist bundles → write RCA_ATTRIBUTED (atomic).

    Args:
        anomaly_id: Anomaly to analyze.
        run_id: RCA run identifier.
        graph_client: Neo4jClient.
        graph_writer: GraphWriter.
        evidence_store: EvidenceStore.
        trigger: "auto" or "manual".
        override: Manual override when accepted exists.

    Returns:
        RCARunResult or None if blocked/failed.
    """
    # Stub: return None
    return None
