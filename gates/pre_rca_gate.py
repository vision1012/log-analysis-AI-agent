"""
Pre-RCA gate.

Runs before RCA execution for a given anomaly_id.
Blocks auto-run if accepted attribution exists; degrades when deployments missing.
Ensures idempotency (no duplicate candidates for same run_id).
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
    severity: str  # "blocker" | "degrade"
    message: str
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None


@dataclass
class PreRCAGateResult:
    """Result of pre-RCA gate."""

    result: GateResult
    anomaly_id: str
    violations: list[Violation]
    accepted_block: bool = False
    excluded_deployment_ids: list[str] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        """Human-readable reasons for the result."""
        return [v.message for v in self.violations]


def run_pre_rca_gate(
    client: Neo4jClient,
    anomaly_id: str,
    *,
    run_id: Optional[str] = None,
    trigger: str = "auto",
    override: bool = False,
) -> PreRCAGateResult:
    """
    Run pre-RCA gate for an anomaly.

    Checks:
    - Block if anomaly has accepted RCA_ATTRIBUTED and trigger=auto (unless override)
    - Block if run_id already has RCA_ATTRIBUTED for this anomaly (idempotency)
    - Degrade if deployments missing or backfill pending
    - Block on structural violations (I1, I2, I6, I12)

    Args:
        client: Neo4jClient for read-only queries.
        anomaly_id: Anomaly to check.
        run_id: RCA run / idempotency key. If provided, blocks when run already wrote candidates.
        trigger: "auto" or "manual".
        override: If True, proceed even when accepted attribution exists.

    Returns:
        PASS/BLOCK/DEGRADE with reasons.
    """
    violations: list[Violation] = []
    accepted_block = False

    # 1. Accepted block: auto-run must not supersede accepted
    if trigger == "auto" and not override:
        has_accepted = _has_accepted_attribution(client, anomaly_id)
        if has_accepted:
            violations.append(
                Violation(
                    invariant_id="accepted_block",
                    severity="blocker",
                    message="Anomaly has accepted attribution; auto-run blocked to avoid superseding",
                    entity_id=anomaly_id,
                    entity_type="Anomaly",
                )
            )
            accepted_block = True

    # 2. Idempotency: run_id already has candidates for this anomaly
    if run_id:
        has_same_run = _has_rca_attributed_for_run(client, anomaly_id, run_id)
        if has_same_run:
            violations.append(
                Violation(
                    invariant_id="I8",
                    severity="blocker",
                    message=f"RCA run {run_id} already has candidates for this anomaly; skip (idempotency)",
                    entity_id=anomaly_id,
                    entity_type="Anomaly",
                )
            )

    # 3. Structural checks (I1, I2, I6, I12)
    struct = _fetch_structural(client, anomaly_id)
    if not struct:
        violations.append(
            Violation(
                invariant_id="I12",
                severity="blocker",
                message="Anomaly not found",
                entity_id=anomaly_id,
                entity_type="Anomaly",
            )
        )
    else:
        if not struct.get("has_timestamp"):
            violations.append(
                Violation(
                    invariant_id="I12",
                    severity="blocker",
                    message="Anomaly missing timestamp",
                    entity_id=anomaly_id,
                    entity_type="Anomaly",
                )
            )
        if not struct.get("has_frames"):
            violations.append(
                Violation(
                    invariant_id="I1",
                    severity="blocker",
                    message="Anomaly has no HAS_FRAME edges",
                    entity_id=anomaly_id,
                    entity_type="Anomaly",
                )
            )
        elif struct.get("entire_trace_unresolved"):
            violations.append(
                Violation(
                    invariant_id="I2",
                    severity="blocker",
                    message="Entire trace unresolved",
                    entity_id=anomaly_id,
                    entity_type="Anomaly",
                )
            )
        elif struct.get("resolved_missing_in_file"):
            violations.append(
                Violation(
                    invariant_id="I2",
                    severity="blocker",
                    message="Resolved StackFrame(s) missing IN_FILE",
                    entity_id=anomaly_id,
                    entity_type="Anomaly",
                )
            )
        if struct.get("frame_order_invalid"):
            violations.append(
                Violation(
                    invariant_id="I6",
                    severity="blocker",
                    message="frame_order invalid (duplicate or non-contiguous)",
                    entity_id=anomaly_id,
                    entity_type="Anomaly",
                )
            )

    # 4. Deployments missing / backfill pending → DEGRADE
    deployment_status = _check_deployments(client, anomaly_id, struct)
    if deployment_status.get("degraded"):
        violations.append(
            Violation(
                invariant_id="I13",
                severity="degrade",
                message=deployment_status.get("reason", "Deployments missing or backfill pending"),
                entity_id=anomaly_id,
                entity_type="Anomaly",
            )
        )
        excluded = deployment_status.get("excluded_deployment_ids", [])
    else:
        excluded = []

    # Determine result
    has_blocker = any(v.severity == "blocker" for v in violations)
    has_degrade = any(v.severity == "degrade" for v in violations)

    if has_blocker:
        result = GateResult.BLOCK
    elif has_degrade:
        result = GateResult.DEGRADE
    else:
        result = GateResult.PASS

    return PreRCAGateResult(
        result=result,
        anomaly_id=anomaly_id,
        violations=violations,
        accepted_block=accepted_block,
        excluded_deployment_ids=excluded,
    )


def _has_accepted_attribution(client: Neo4jClient, anomaly_id: str) -> bool:
    """Check if anomaly has any RCA_ATTRIBUTED with status=accepted."""
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->()
    WHERE r.status = 'accepted'
    RETURN count(r) AS n
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return rows[0]["n"] > 0 if rows else False


def _has_rca_attributed_for_run(
    client: Neo4jClient, anomaly_id: str, run_id: str
) -> bool:
    """Check if anomaly already has RCA_ATTRIBUTED from this run_id."""
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->()
    WHERE r.run_id = $run_id
    RETURN count(r) AS n
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id, "run_id": run_id})
    return rows[0]["n"] > 0 if rows else False


def _fetch_structural(client: Neo4jClient, anomaly_id: str) -> Optional[dict[str, Any]]:
    """
    Fetch structural state: timestamp, HAS_FRAME, frame resolution, IN_FILE, frame_order.
    Returns None if anomaly not found.
    """
    # Anomaly + timestamp
    q_anomaly = """
    MATCH (a:Anomaly {id: $anomaly_id})
    RETURN a.timestamp AS timestamp
    """
    anomaly_rows = client.execute_read(q_anomaly, {"anomaly_id": anomaly_id})
    if not anomaly_rows:
        return None

    has_timestamp = anomaly_rows[0].get("timestamp") is not None

    # Frames with resolution and IN_FILE
    q_frames = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:HAS_FRAME]->(s:StackFrame)
    OPTIONAL MATCH (s)-[:IN_FILE]->(f:File)
    RETURN r.frame_order AS frame_order,
           s.resolution AS resolution,
           (f IS NOT NULL) AS has_in_file
    """
    frame_rows = client.execute_read(q_frames, {"anomaly_id": anomaly_id})

    if not frame_rows:
        return {
            "has_timestamp": has_timestamp,
            "has_frames": False,
            "entire_trace_unresolved": False,
            "resolved_missing_in_file": False,
            "frame_order_invalid": False,
        }

    frame_orders = [r["frame_order"] for r in frame_rows if r.get("frame_order") is not None]
    resolved_count = sum(1 for r in frame_rows if (r.get("resolution") or "resolved") == "resolved")
    unresolved_count = sum(1 for r in frame_rows if r.get("resolution") == "unknown")
    resolved_missing = any(
        (r.get("resolution") or "resolved") == "resolved" and not r.get("has_in_file")
        for r in frame_rows
    )

    # frame_order unique and contiguous (0 to n-1)
    n = len(frame_rows)
    expected = set(range(n))
    actual = set(frame_orders)
    frame_order_invalid = actual != expected or len(frame_orders) != n

    return {
        "has_timestamp": has_timestamp,
        "has_frames": True,
        "entire_trace_unresolved": resolved_count == 0 and n > 0,
        "resolved_missing_in_file": resolved_missing,
        "frame_order_invalid": frame_order_invalid,
    }


def _check_deployments(
    client: Neo4jClient, anomaly_id: str, struct: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """
    Check deployment correlation scope. Degrade if no deployments or missing timestamps.
    """
    if not struct or not struct.get("has_frames"):
        return {"degraded": False}

    # Get anomaly service_ref and timestamp
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})
    RETURN a.service_ref AS service_ref, a.timestamp AS timestamp
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    if not rows:
        return {"degraded": False}

    service_ref = rows[0].get("service_ref")
    anomaly_ts = rows[0].get("timestamp")

    if not service_ref:
        return {"degraded": True, "reason": "Anomaly missing service_ref; deployment correlation unavailable"}

    if not anomaly_ts:
        return {"degraded": True, "reason": "Anomaly missing timestamp; deployment correlation unavailable"}

    # Deployments in scope: same service_ref, timestamp before anomaly
    q_deploy = """
    MATCH (d:Deployment)
    WHERE d.service_ref = $service_ref
    RETURN d.id AS deployment_id, d.timestamp AS deployment_ts
    """
    deploy_rows = client.execute_read(q_deploy, {"service_ref": service_ref})

    excluded: list[str] = []
    valid_count = 0

    for r in deploy_rows:
        dep_id = r.get("deployment_id")
        dep_ts = r.get("deployment_ts")
        if dep_ts is None:
            if dep_id:
                excluded.append(dep_id)
        else:
            valid_count += 1

    if valid_count == 0:
        return {
            "degraded": True,
            "reason": "No deployments in correlation scope (deployments missing or backfill pending)",
            "excluded_deployment_ids": excluded,
        }
    if excluded:
        return {
            "degraded": True,
            "reason": f"Some deployments missing timestamp (excluded: {len(excluded)})",
            "excluded_deployment_ids": excluded,
        }

    return {"degraded": False, "excluded_deployment_ids": []}
