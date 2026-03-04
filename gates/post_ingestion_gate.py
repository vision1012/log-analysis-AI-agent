"""
Post-ingestion gate.

Validates structural integrity after ingestion for a given anomaly_id.
Checks: I1 (HAS_FRAME), I2 (IN_FILE for resolved frames), I12 (timestamps).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from graph.neo4j_client import Neo4jClient


class GateResult(str, Enum):
    """Gate outcome."""

    PASS = "pass"
    BLOCK = "block"
    DEGRADE = "degrade"


@dataclass
class Violation:
    """Single invariant violation."""

    invariant_id: str
    severity: str  # "blocker" | "degrade" | "warn"
    message: str
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    affected_signals: list[str] = field(default_factory=list)


@dataclass
class PostIngestionGateResult:
    """Result of post-ingestion gate."""

    result: GateResult
    anomaly_id: str
    batch_id: Optional[str]
    violations: list[Violation]
    affected_signals: list[str] = field(default_factory=list)
    frame_count: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    frames_missing_in_file: list[str] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        """Human-readable reasons for the result."""
        return [v.message for v in self.violations]


# Signals affected by each violation type (from confidence_signals.md)
_BLOCKER_SIGNALS = [
    "top_frame",
    "frame_depth",
    "trace_completeness",
    "last_touch_recency",
    "deploy_proximity",
    "deploy_recency_rank",
    "file_frame_count",
    "path_exclusion",
    "deployment_timing_valid",
]
_TRACE_PARTIAL_SIGNALS = ["trace_completeness"]
_MISSING_IN_FILE_SIGNALS = ["last_touch_recency", "file_frame_count", "path_exclusion"]
_MISSING_TIMESTAMP_SIGNALS = [
    "deployment_timing_valid",
    "last_touch_recency",
    "deploy_proximity",
]


def run_post_ingestion_gate(
    client: Neo4jClient,
    anomaly_id: str,
    *,
    batch_id: Optional[str] = None,
) -> PostIngestionGateResult:
    """
    Run post-ingestion gate for a single anomaly.

    Validates:
    - I1: Anomaly has at least one HAS_FRAME
    - I2: Resolved StackFrames have IN_FILE; entire trace unresolved = BLOCK
    - I12: Anomaly has timestamp

    Args:
        client: Neo4jClient for read-only queries.
        anomaly_id: Anomaly to validate.
        batch_id: Optional ingestion batch identifier for audit.

    Returns:
        Structured result with PASS/BLOCK/DEGRADE, reasons, and affected signals.
    """
    violations: list[Violation] = []
    affected_signals: set[str] = set()

    # 1. Check anomaly exists and has timestamp (I12)
    anomaly = _fetch_anomaly(client, anomaly_id)
    if not anomaly:
        violations.append(
            Violation(
                invariant_id="I12",
                severity="blocker",
                message="Anomaly not found",
                entity_id=anomaly_id,
                entity_type="Anomaly",
                affected_signals=_BLOCKER_SIGNALS,
            )
        )
        affected_signals.update(_BLOCKER_SIGNALS)
        return _build_result(
            anomaly_id, batch_id, violations, affected_signals, 0, 0, 0, []
        )

    if not anomaly.get("timestamp"):
        violations.append(
            Violation(
                invariant_id="I12",
                severity="blocker",
                message="Anomaly missing timestamp",
                entity_id=anomaly_id,
                entity_type="Anomaly",
                affected_signals=_MISSING_TIMESTAMP_SIGNALS,
            )
        )
        affected_signals.update(_MISSING_TIMESTAMP_SIGNALS)

    # 2. Check HAS_FRAME (I1)
    frames = _fetch_frames_with_in_file(client, anomaly_id)
    if not frames:
        violations.append(
            Violation(
                invariant_id="I1",
                severity="blocker",
                message="Anomaly has no HAS_FRAME edges",
                entity_id=anomaly_id,
                entity_type="Anomaly",
                affected_signals=_BLOCKER_SIGNALS,
            )
        )
        affected_signals.update(_BLOCKER_SIGNALS)
        return _build_result(
            anomaly_id, batch_id, violations, affected_signals, 0, 0, 0, []
        )

    # 3. Check I2: resolved frames have IN_FILE; handle resolution=unknown
    resolved_count = sum(1 for f in frames if f.get("resolution") == "resolved")
    unresolved_count = sum(1 for f in frames if f.get("resolution") == "unknown")
    frames_missing_in_file: list[str] = []

    for f in frames:
        resolution = f.get("resolution") or "resolved"
        has_in_file = f.get("has_in_file", False)
        frame_id = f.get("frame_id", "")

        if resolution == "resolved" and not has_in_file:
            frames_missing_in_file.append(frame_id)
            violations.append(
                Violation(
                    invariant_id="I2",
                    severity="blocker",
                    message="Resolved StackFrame missing IN_FILE",
                    entity_id=frame_id,
                    entity_type="StackFrame",
                    affected_signals=_MISSING_IN_FILE_SIGNALS,
                )
            )
            affected_signals.update(_MISSING_IN_FILE_SIGNALS)

    # Entire trace unresolved = BLOCK
    if resolved_count == 0 and len(frames) > 0:
        violations.append(
            Violation(
                invariant_id="I2",
                severity="blocker",
                message="Entire trace unresolved (no frames with resolution=resolved)",
                entity_id=anomaly_id,
                entity_type="Anomaly",
                affected_signals=_TRACE_PARTIAL_SIGNALS,
            )
        )
        affected_signals.update(_TRACE_PARTIAL_SIGNALS)

    # Partial trace (some unresolved) = DEGRADE
    if unresolved_count > 0 and resolved_count > 0 and not frames_missing_in_file:
        violations.append(
            Violation(
                invariant_id="I2",
                severity="degrade",
                message=f"Partial trace: {unresolved_count} frame(s) with resolution=unknown",
                entity_id=anomaly_id,
                entity_type="Anomaly",
                affected_signals=_TRACE_PARTIAL_SIGNALS,
            )
        )
        affected_signals.update(_TRACE_PARTIAL_SIGNALS)

    return _build_result(
        anomaly_id,
        batch_id,
        violations,
        affected_signals,
        len(frames),
        resolved_count,
        unresolved_count,
        frames_missing_in_file,
    )


def run_post_ingestion_gate_batch(
    client: Neo4jClient,
    anomaly_ids: list[str],
    *,
    batch_id: Optional[str] = None,
) -> list[PostIngestionGateResult]:
    """
    Run post-ingestion gate for multiple anomalies.

    Returns one result per anomaly_id, in order.
    """
    return [
        run_post_ingestion_gate(client, aid, batch_id=batch_id) for aid in anomaly_ids
    ]


def _fetch_anomaly(client: Neo4jClient, anomaly_id: str) -> Optional[dict[str, Any]]:
    """Fetch anomaly with timestamp. Returns None if not found."""
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})
    RETURN a.id AS id, a.timestamp AS timestamp
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return rows[0] if rows else None


def _fetch_frames_with_in_file(
    client: Neo4jClient, anomaly_id: str
) -> list[dict[str, Any]]:
    """
    Fetch all StackFrames linked via HAS_FRAME, with resolution and IN_FILE presence.
    """
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:HAS_FRAME]->(s:StackFrame)
    OPTIONAL MATCH (s)-[:IN_FILE]->(f:File)
    RETURN s.id AS frame_id,
           s.resolution AS resolution,
           (f IS NOT NULL) AS has_in_file
    ORDER BY r.frame_order
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return [dict(r) for r in rows]


def _build_result(
    anomaly_id: str,
    batch_id: Optional[str],
    violations: list[Violation],
    affected_signals: set[str],
    frame_count: int,
    resolved_count: int,
    unresolved_count: int,
    frames_missing_in_file: list[str],
) -> PostIngestionGateResult:
    """Determine PASS/BLOCK/DEGRADE and build result."""
    has_blocker = any(v.severity == "blocker" for v in violations)
    has_degrade = any(v.severity == "degrade" for v in violations)

    if has_blocker:
        result = GateResult.BLOCK
    elif has_degrade:
        result = GateResult.DEGRADE
    else:
        result = GateResult.PASS

    return PostIngestionGateResult(
        result=result,
        anomaly_id=anomaly_id,
        batch_id=batch_id,
        violations=violations,
        affected_signals=sorted(affected_signals),
        frame_count=frame_count,
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        frames_missing_in_file=frames_missing_in_file,
    )
