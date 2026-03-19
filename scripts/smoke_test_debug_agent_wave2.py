#!/usr/bin/env python3
"""
Smoke test for debug_agent Wave 2 orchestration.

Steps:
1) create or reuse a sample anomaly
2) run full Wave 2 debug-agent pipeline
3) print key investigation fields
4) validate structured output + safe fallback behavior

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=xxx \
      python scripts/smoke_test_debug_agent_wave2.py
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
    trace_ref = "smoke-debug-wave2-trace"
    repo_ref = "smoke-debug-wave2-repo"
    service_ref = "smoke-debug-wave2-service"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    writer.upsert_anomaly(anomaly_id, ts, trace_ref=trace_ref, window_id="smoke-debug-wave2-window")
    client.execute_write(
        "MATCH (a:Anomaly {id: $id}) SET a.service_ref = $service_ref",
        {"id": anomaly_id, "service_ref": service_ref},
    )
    client.execute_write(
        """
        MATCH (a:Anomaly {id: $id})
        SET a.title = $title, a.message = $message, a.severity = $severity, a.score = $score
        """,
        {
            "id": anomaly_id,
            "title": "Timeout in API handler",
            "message": "Request timed out while waiting for downstream response",
            "severity": "high",
            "score": 0.86,
        },
    )

    writer.upsert_stackframe("dbg2-f0", trace_ref, symbol_name="main", frame_order=0, resolution="resolved")
    writer.upsert_stackframe("dbg2-f1", trace_ref, symbol_name="handler", frame_order=1, resolution="resolved")
    writer.upsert_stackframe("dbg2-f2", trace_ref, symbol_name="process", frame_order=2, resolution="resolved")

    writer.link_has_frame(anomaly_id, "dbg2-f0", 0)
    writer.link_has_frame(anomaly_id, "dbg2-f1", 1)
    writer.link_has_frame(anomaly_id, "dbg2-f2", 2)

    writer.upsert_file("src/debug_wave2/foo.py", repo_ref)
    writer.upsert_file("src/debug_wave2/bar.py", repo_ref)

    from graph.writer import _compute_file_id
    foo_id = _compute_file_id(repo_ref, "src/debug_wave2/foo.py")
    bar_id = _compute_file_id(repo_ref, "src/debug_wave2/bar.py")
    writer.link_in_file("dbg2-f0", foo_id)
    writer.link_in_file("dbg2-f1", foo_id)
    writer.link_in_file("dbg2-f2", bar_id)

    commit_sha = "debugwave2abc123"
    deploy_id = "debug-wave2-deploy-001"
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
    run_id = f"smoke-debug-wave2-{uuid.uuid4().hex[:8]}"
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
        "triage_summary",
        "root_cause_candidates",
        "primary_candidate",
        "confidence_summary",
        "evidence_highlights",
        "similar_incidents",
        "historical_patterns_summary",
        "recurrence_signals",
        "explanation_summary",
        "created_at",
        "status",
    )
    for k in required_report_keys:
        if k not in report:
            errors.append(f"missing investigation_report key: {k}")

    # Safe fallback behavior check:
    # explanation step may fail, but report should still be present and include summary.
    steps = result.get("steps") or []
    if isinstance(steps, list):
        exp_steps = [s for s in steps if isinstance(s, dict) and s.get("kind") == "explanation"]
        if exp_steps:
            exp_ok = bool(exp_steps[0].get("success"))
            if not exp_ok and not report.get("explanation_summary"):
                errors.append("explanation failed but explanation_summary is missing in report")

    return len(errors) == 0, errors


def main() -> None:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = _require_password()
    anomaly_id = os.environ.get("SMOKE_DEBUG_AGENT_WAVE2_ANOMALY_ID", "smoke-debug-agent-wave2-001")

    from debug_agent.orchestrator import run_debug_session
    from graph.migrations import apply_migrations
    from graph.neo4j_client import Neo4jClient

    apply_migrations(uri, user, password)
    client = Neo4jClient(uri, user, password)
    client.connect()

    try:
        run_id = _ensure_candidates(client, anomaly_id)
        print(f"[ready] anomaly={anomaly_id} run_id={run_id or 'latest'}")

        # Wave 2 full pipeline
        result = run_debug_session(anomaly_id, run_id=run_id or None)
        report = result.get("investigation_report") or {}

        print("\n=== Debug Agent Wave 2 Investigation ===")
        print(f"anomaly_id: {result.get('anomaly_id')}")
        print(f"triage summary: {report.get('triage_summary')}")
        severity = (report.get("triage_summary") or "").split("severity=")
        if len(severity) > 1:
            print(f"severity: {severity[1].split(',')[0]}")
        else:
            print("severity: unknown")

        primary = report.get("primary_candidate") or {}
        print(f"primary RCA candidate: {primary.get('path') or primary.get('file_id')}")
        similar_incidents = report.get("similar_incidents") or []
        print(f"similar incidents count: {len(similar_incidents)}")
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

        print("\nDEBUG_AGENT_WAVE2_COMPLETE")
    finally:
        client.close()


if __name__ == "__main__":
    main()

