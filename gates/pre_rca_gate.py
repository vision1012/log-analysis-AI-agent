"""
Pre-RCA gate.

Runs before RCA execution. Validates I1, I2, I6, I8, I9, I12; degrades on I10, I11, I13, I15.
Blocks auto-run if anomaly has accepted attribution (unless manual override).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

# from graph.neo4j_client import Neo4jClient


class GateResult(str, Enum):
    """Gate outcome."""

    PASS = "pass"
    BLOCK = "block"
    DEGRADE = "degrade"


@dataclass
class PreRCAGateResult:
    """Result of pre-RCA gate."""

    result: GateResult
    anomaly_id: str
    violations: list[dict[str, Any]]
    excluded_deployment_ids: Optional[list[str]] = None
    accepted_block: bool = False


def run_pre_rca_gate(
    client: Any,
    anomaly_id: str,
    *,
    trigger: str = "auto",
    override: bool = False,
) -> PreRCAGateResult:
    """
    Run pre-RCA gate for an anomaly.

    Args:
        client: Neo4jClient for read-only queries.
        anomaly_id: Anomaly to check.
        trigger: "auto" or "manual".
        override: If True, proceed even when accepted attribution exists.

    Returns:
        Gate result. Blocks if accepted exists and trigger=auto and not override.
    """
    # Implement I1, I2, I6, I8, I9, I12; degrade I10, I11, I13, I15
    # Check accepted attribution; block auto-run if present and not override
    return PreRCAGateResult(
        result=GateResult.PASS,
        anomaly_id=anomaly_id,
        violations=[],
        accepted_block=False,
    )
