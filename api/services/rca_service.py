"""
RCA orchestration logic. Called by API and jobs.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from artifacts.evidence_store import EvidenceStore
from graph.neo4j_client import Neo4jClient
from graph.writer import GraphWriter
from graphrag.explanation_generator import generate_explanation
from graphrag.llm_client import GraphRAGLLMClient

from jobs.job_locking import acquire_lock, is_locked, release_lock
from rca_engine import run_deterministic_rca


def _get_neo4j_client() -> Neo4jClient:
    """Create Neo4j client from env."""
    return Neo4jClient.from_env()


def _get_evidence_store() -> EvidenceStore:
    """Create evidence store. Uses EVIDENCE_STORE_DIR or temp."""
    from pathlib import Path
    import tempfile
    base = os.environ.get("EVIDENCE_STORE_DIR") or tempfile.gettempdir()
    from artifacts.evidence_store import LocalFileEvidenceStore
    return LocalFileEvidenceStore(Path(base) / "evidence_bundles")


def _run_summary(
    status: str,
    anomaly_id: str,
    run_id: Optional[str] = None,
    attribution_count: Optional[int] = None,
    bundle_ids: Optional[list[str]] = None,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Structured run summary."""
    out: dict[str, Any] = {
        "status": status,
        "anomaly_id": anomaly_id,
        "run_id": run_id,
        "attribution_count": attribution_count,
        "bundle_ids": bundle_ids or [],
    }
    if reason:
        out["reason"] = reason
    return out


def _get_run_summary_for_run(
    client: Neo4jClient,
    anomaly_id: str,
    run_id: str,
) -> Optional[dict[str, Any]]:
    """Fetch existing run summary if run_id has RCA_ATTRIBUTED edges."""
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(f:File)
    WHERE r.run_id = $run_id
    RETURN r.evidence_ref AS evidence_ref
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id, "run_id": run_id})
    if not rows:
        return None
    bundle_ids = [r["evidence_ref"] for r in rows if r.get("evidence_ref")]
    return _run_summary(
        status="completed",
        anomaly_id=anomaly_id,
        run_id=run_id,
        attribution_count=len(rows),
        bundle_ids=bundle_ids,
    )


def trigger_auto_rca(anomaly_id: str, *, _lock_held: bool = False) -> dict[str, Any]:
    """
    Trigger auto RCA. Blocked if accepted RCA already exists.
    Rejected if anomaly is locked (run in progress).
    _lock_held: When True, caller owns lock; skip acquire/release.
    """
    if not _lock_held:
        if is_locked(anomaly_id):
            return _run_summary(
                status="rejected",
                anomaly_id=anomaly_id,
                reason="Anomaly locked; run already in progress",
            )
        if not acquire_lock(anomaly_id, timeout_sec=0):
            return _run_summary(
                status="rejected",
                anomaly_id=anomaly_id,
                reason="Could not acquire lock; run already in progress",
            )
    try:
        result = run_rca(anomaly_id, trigger_type="auto", override=False)
        if result is None:
            return _run_summary(
                status="blocked",
                anomaly_id=anomaly_id,
                reason="Auto-run blocked (accepted attribution exists or gate failed)",
            )
        return _run_summary(
            status="completed",
            anomaly_id=result["anomaly_id"],
            run_id=result["run_id"],
            attribution_count=result["attribution_count"],
            bundle_ids=result.get("bundle_ids", []),
        )
    finally:
        if not _lock_held:
            release_lock(anomaly_id)


def trigger_manual_rca(
    anomaly_id: str,
    idempotency_key: str,
    force: bool = False,
    *,
    _lock_held: bool = False,
) -> dict[str, Any]:
    """
    Trigger manual RCA with idempotency key.
    Same key returns existing result (idempotent).
    force=True allows superseding accepted attributions.
    Rejected if anomaly is locked.
    _lock_held: When True, caller owns lock; skip acquire/release.
    """
    if not _lock_held:
        if is_locked(anomaly_id):
            return _run_summary(
                status="rejected",
                anomaly_id=anomaly_id,
                run_id=idempotency_key,
                reason="Anomaly locked; run already in progress",
            )
        if not acquire_lock(anomaly_id, timeout_sec=0):
            return _run_summary(
                status="rejected",
                anomaly_id=anomaly_id,
                run_id=idempotency_key,
                reason="Could not acquire lock; run already in progress",
            )
    try:
        client = _get_neo4j_client()
        if not getattr(client, "_driver", None):
            client.connect()
        try:
            existing = _get_run_summary_for_run(client, anomaly_id, idempotency_key)
            if existing:
                return _run_summary(
                    status="completed",
                    anomaly_id=anomaly_id,
                    run_id=idempotency_key,
                    attribution_count=existing["attribution_count"],
                    bundle_ids=existing.get("bundle_ids", []),
                    reason="Idempotent; run already exists",
                )
        finally:
            client.close()

        result = run_rca(
            anomaly_id,
            trigger_type="manual",
            run_id=idempotency_key,
            override=force,
        )
        if result is None:
            return _run_summary(
                status="blocked",
                anomaly_id=anomaly_id,
                run_id=idempotency_key,
                reason="Manual run blocked (gate failed)",
            )
        return _run_summary(
            status="completed",
            anomaly_id=result["anomaly_id"],
            run_id=result["run_id"],
            attribution_count=result["attribution_count"],
            bundle_ids=result.get("bundle_ids", []),
        )
    finally:
        if not _lock_held:
            release_lock(anomaly_id)


def run_rca(
    anomaly_id: str,
    trigger_type: str = "manual",
    *,
    run_id: Optional[str] = None,
    override: bool = False,
    graph_client: Optional[Neo4jClient] = None,
    graph_writer: Optional[GraphWriter] = None,
    evidence_store: Optional[EvidenceStore] = None,
) -> Optional[dict[str, Any]]:
    """
    Run deterministic RCA for one anomaly.

    Returns dict with run_id, anomaly_id, attribution_count, bundle_ids,
    or None if blocked/failed.
    """
    client = graph_client or _get_neo4j_client()
    writer = graph_writer or GraphWriter(client)
    store = evidence_store or _get_evidence_store()
    own_client = graph_client is None

    if not getattr(client, "_driver", None):
        client.connect()

    try:
        result = run_deterministic_rca(
            anomaly_id,
            trigger_type,
            graph_client=client,
            graph_writer=writer,
            evidence_store=store,
            run_id=run_id,
            override=override,
        )
        if result is None:
            return None
        return {
            "run_id": result.run_id,
            "anomaly_id": result.anomaly_id,
            "attribution_count": result.attribution_count,
            "bundle_ids": result.bundle_ids,
        }
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()


def get_rca_run_status(anomaly_id: str) -> dict[str, Any]:
    """
    Get current lock/run state for an anomaly.
    Returns {anomaly_id, locked}.
    """
    return {"anomaly_id": anomaly_id, "locked": is_locked(anomaly_id)}


def get_rca_results(
    anomaly_id: str,
    *,
    graph_client: Optional[Neo4jClient] = None,
) -> list[dict[str, Any]]:
    """
    Get current RCA_ATTRIBUTED candidates for an anomaly.

    Returns list of {file_id, path, confidence, run_id, status, evidence_ref}.
    """
    client = graph_client or _get_neo4j_client()
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()

    try:
        q = """
        MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(f:File)
        WHERE r.status IN ['candidate', 'accepted']
        RETURN f.file_id AS file_id, f.path AS path,
               r.confidence AS confidence, r.run_id AS run_id,
               r.status AS status, r.evidence_ref AS evidence_ref
        ORDER BY r.confidence DESC
        """
        rows = client.execute_read(q, {"anomaly_id": anomaly_id})
        return [dict(r) for r in rows]
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()


def get_rca_result_view(
    anomaly_id: str,
    *,
    graph_client: Optional[Neo4jClient] = None,
) -> dict[str, Any]:
    """
    Return RCA results for an anomaly in structured view.

    Shape:
        anomaly_id, current_status, accepted_root_cause, candidate_root_causes[],
        latest_run_id, evidence_refs[], last_updated_at
    """
    client = graph_client or _get_neo4j_client()
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()

    try:
        q = """
        MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(f:File)
        WHERE r.status IN ['candidate', 'accepted']
        RETURN f.file_id AS file_id, f.path AS path,
               r.confidence AS confidence, r.run_id AS run_id,
               r.status AS status, r.evidence_ref AS evidence_ref,
               r.created_at AS created_at, r.feedback_at AS feedback_at
        ORDER BY r.confidence DESC
        """
        rows = client.execute_read(q, {"anomaly_id": anomaly_id})

        accepted: Optional[dict[str, Any]] = None
        candidates: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        latest_run_id: Optional[str] = None
        last_updated_at: Optional[str] = None

        for r in rows:
            row = dict(r)
            ref = row.get("evidence_ref")
            if ref:
                evidence_refs.append(ref)

            item = {
                "file_id": row["file_id"],
                "path": row.get("path") or "",
                "confidence": row.get("confidence") or 0.0,
                "run_id": row.get("run_id"),
                "evidence_ref": ref,
            }

            ts_candidates = []
            if row.get("created_at"):
                ts_candidates.append(row["created_at"])
            if row.get("feedback_at"):
                ts_candidates.append(row["feedback_at"])
            if ts_candidates:
                row_latest = max(ts_candidates)
                if last_updated_at is None or row_latest > last_updated_at:
                    last_updated_at = row_latest
                    latest_run_id = row.get("run_id")

            if row.get("status") == "accepted":
                accepted = item
            else:
                candidates.append(item)

        if last_updated_at is None and rows:
            for r in rows:
                if r.get("created_at"):
                    last_updated_at = r["created_at"]
                if latest_run_id is None and r.get("run_id"):
                    latest_run_id = r["run_id"]
                if last_updated_at and latest_run_id:
                    break

        current_status = _derive_current_status(accepted, candidates) or "empty"

        return {
            "anomaly_id": anomaly_id,
            "current_status": current_status,
            "accepted_root_cause": accepted,
            "candidate_root_causes": candidates,
            "latest_run_id": latest_run_id,
            "evidence_refs": evidence_refs,
            "last_updated_at": last_updated_at,
        }
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()


def get_rca_explanation(
    anomaly_id: str,
    *,
    run_id: Optional[str] = None,
    graph_client: Optional[Neo4jClient] = None,
    evidence_store: Optional[EvidenceStore] = None,
    llm_client: Optional[GraphRAGLLMClient] = None,
) -> dict[str, Any]:
    """
    Build RCA explanation for latest deterministic run (or provided run_id).

    Keeps deterministic RCA and explanation layer separate:
    - deterministic RCA results remain source of truth
    - GraphRAG only explains those results
    """
    client = graph_client or _get_neo4j_client()
    own_client = graph_client is None
    if not getattr(client, "_driver", None):
        client.connect()

    store = evidence_store or _get_evidence_store()
    explainer = llm_client or GraphRAGLLMClient()

    try:
        return generate_explanation(
            anomaly_id,
            graph_client=client,
            evidence_store=store,
            llm_client=explainer,
            run_id=run_id,
        )
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()


def _derive_current_status(
    accepted: Optional[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> Optional[str]:
    """Derive current_status from accepted/candidates."""
    if accepted:
        return "has_accepted"
    if candidates:
        return "has_candidates"
    return None
