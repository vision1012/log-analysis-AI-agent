#!/usr/bin/env python3
"""
Smoke test for debug_agent Wave 1 orchestration.

Steps:
1) create or reuse a sample anomaly
2) run debug agent orchestrator (Wave 1: RCA -> Evidence -> Explanation)
3) print key investigation fields
4) verify structured investigation result is returned

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=xxx \
      python scripts/smoke_test_debug_agent_wave1.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _require_password() -> str:
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("NEO4J_PASSWORD required", file=sys.stderr)
        sys.exit(1)
    return password


def _has_candidates(client, anomaly_id: str) -> bool:
    q = """
    MATCH (:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(:File)
    WHERE r.status IN ['candidate', 'accepted']
    RETURN count(r) AS n
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return bool(rows and int(rows[0].get("n", 0) or 0) > 0)


def _latest_run_id(client, anomaly_id: str) -> str:
    q = """
    MATCH (:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(:File)
    WHERE r.status IN ['candidate', 'accepted']
    RETURN r.run_id AS run_id, coalesce(r.created_at, '') AS ts
    ORDER BY ts DESC
    LIMIT 1
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return (rows[0].get("run_id") if rows else "") or ""


def _create_test_anomaly(client, writer, anomaly_id: str) -> None:
    """Create minimal graph state required by deterministic RCA."""
    trace_ref = "smoke-debug-wave1-trace"
    repo_ref = "smoke-debug-wave1-repo"
    service_ref = "smoke-debug-wave1-service"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    writer.upsert_anomaly(anomaly_id, ts, trace_ref=trace_ref, window_id="smoke-debug-wave1-window")
    client.execute_write(
        "MATCH (a:Anomaly {id: $id}) SET a.service_ref = $service_ref",
        {"id": anomaly_id, "service_ref": service_ref},
    )

    writer.upsert_stackframe("dbg-f0", trace_ref, symbol_name="main", frame_order=0, resolution="resolved")
    writer.upsert_stackframe("dbg-f1", trace_ref, symbol_name="handler", frame_order=1, resolution="resolved")
    writer.upsert_stackframe("dbg-f2", trace_ref, symbol_name="process", frame_order=2, resolution="resolved")

    writer.link_has_frame(anomaly_id, "dbg-f0", 0)
    writer.link_has_frame(anomaly_id, "dbg-f1", 1)
    writer.link_has_frame(anomaly_id, "dbg-f2", 2)

    writer.upsert_file("src/debug/foo.py", repo_ref)
    writer.upsert_file("src/debug/bar.py", repo_ref)

    from graph.writer import _compute_file_id

    foo_id = _compute_file_id(repo_ref, "src/debug/foo.py")
    bar_id = _compute_file_id(repo_ref, "src/debug/bar.py")

    writer.link_in_file("dbg-f0", foo_id)
    writer.link_in_file("dbg-f1", foo_id)
    writer.link_in_file("dbg-f2", bar_id)

    commit_sha = "debugwave1abc123"
    deploy_id = "debug-wave1-deploy-001"
    writer.upsert_commit(commit_sha, repo_ref, ts)
    writer.upsert_deployment(deploy_id, ts, service_ref=service_ref)
    writer.link_touched(commit_sha, repo_ref, foo_id)
    writer.link_touched(commit_sha, repo_ref, bar_id)
    writer.link_deployed_commit(deploy_id, commit_sha, repo_ref)


def _ensure_candidates(client, anomaly_id: str) -> str:
    """Create/reuse anomaly and ensure deterministic RCA candidates exist."""
    if _has_candidates(client, anomaly_id):
        return _latest_run_id(client, anomaly_id)

    from api.services.rca_service import run_rca
    from artifacts.evidence_store import LocalFileEvidenceStore
    from graph.writer import GraphWriter

    writer = GraphWriter(client)
    _create_test_anomaly(client, writer, anomaly_id)

    evidence_base = os.environ.get("EVIDENCE_STORE_DIR") or tempfile.gettempdir()
    store = LocalFileEvidenceStore(os.path.join(evidence_base, "evidence_bundles"))
    run_id = f"smoke-debug-wave1-{uuid.uuid4().hex[:8]}"
    result = run_rca(
        anomaly_id,
        trigger_type="manual",
        run_id=run_id,
        override=True,
        graph_client=client,
        graph_writer=writer,
        evidence_store=store,
    )
    if result is None:
        raise RuntimeError("Deterministic RCA did not produce candidates for smoke anomaly.")
    return str(result.get("run_id") or run_id)


def _validate_result_shape(result: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(result, dict):
        return False, ["result is not an object"]
    for key in ("anomaly_id", "run_id", "status", "investigation_report", "steps"):
        if key not in result:
            errors.append(f"missing key: {key}")
    report = result.get("investigation_report")
    if not isinstance(report, dict):
        errors.append("investigation_report must be an object")
        return len(errors) == 0, errors
    required_report_keys = (
        "root_cause_candidates",
        "primary_candidate",
        "confidence_summary",
        "evidence_highlights",
        "explanation_summary",
        "created_at",
        "status",
    )
    for k in required_report_keys:
        if k not in report:
            errors.append(f"missing investigation_report key: {k}")
    return len(errors) == 0, errors


def main() -> None:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = _require_password()
    anomaly_id = os.environ.get("SMOKE_DEBUG_AGENT_ANOMALY_ID", "smoke-debug-agent-wave1-001")

    from debug_agent.orchestrator import run_debug_session
    from graph.migrations import apply_migrations
    from graph.neo4j_client import Neo4jClient

    apply_migrations(uri, user, password)
    client = Neo4jClient(uri, user, password)
    client.connect()

    try:
        run_id = _ensure_candidates(client, anomaly_id)
        if run_id:
            print(f"[ready] anomaly={anomaly_id} run_id={run_id}")
        else:
            print(f"[ready] anomaly={anomaly_id} run_id=latest")

        result = run_debug_session(anomaly_id, run_id=run_id or None)
        report = result.get("investigation_report") or {}

        print("\n=== Debug Agent Wave 1 Investigation ===")
        print(f"anomaly_id: {result.get('anomaly_id')}")
        primary = report.get("primary_candidate") or {}
        print(f"primary RCA candidate: {primary.get('path') or primary.get('file_id')}")
        print(f"confidence summary: {report.get('confidence_summary')}")
        print("evidence highlights:")
        for item in (report.get("evidence_highlights") or []):
            print(f" - {item}")
        print(f"explanation summary: {report.get('explanation_summary')}")

        ok, errors = _validate_result_shape(result)
        print(f"\nstructured result valid: {ok}")
        if not ok:
            print("validation errors:")
            for e in errors:
                print(f" - {e}")
            sys.exit(2)

        print("\nDEBUG_AGENT_WAVE1_COMPLETE")
    finally:
        client.close()


if __name__ == "__main__":
    main()

