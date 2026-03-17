#!/usr/bin/env python3
"""
Smoke test for RCA API flow: create anomaly, run RCA, confirm candidate, verify, rollback.

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=xxx python scripts/smoke_test_rca_api.py

Requires: neo4j driver (pip install neo4j)
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.getLogger("graph").setLevel(logging.WARNING)
logging.getLogger("gates").setLevel(logging.WARNING)
logging.getLogger("rca_engine").setLevel(logging.WARNING)


def _create_test_anomaly(client, writer, anomaly_id: str) -> None:
    """Create anomaly + trace + files + links."""
    trace_ref = "smoke-rca-api-trace"
    repo_ref = "smoke-repo"
    service_ref = "smoke-service"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    writer.upsert_anomaly(anomaly_id, ts, trace_ref=trace_ref, window_id="smoke-rca-w1")
    client.execute_write(
        "MATCH (a:Anomaly {id: $id}) SET a.service_ref = $service_ref",
        {"id": anomaly_id, "service_ref": service_ref},
    )
    writer.upsert_stackframe("rca-f0", trace_ref, symbol_name="main", frame_order=0, resolution="resolved")
    writer.upsert_stackframe("rca-f1", trace_ref, symbol_name="handler", frame_order=1, resolution="resolved")
    writer.upsert_stackframe("rca-f2", trace_ref, symbol_name="process", frame_order=2, resolution="resolved")

    writer.upsert_file("src/foo.py", repo_ref)
    writer.upsert_file("src/bar.py", repo_ref)
    writer.upsert_commit("abc123", repo_ref, ts)
    writer.upsert_deployment("rca-deploy-001", ts, service_ref=service_ref)

    writer.link_has_frame(anomaly_id, "rca-f0", 0)
    writer.link_has_frame(anomaly_id, "rca-f1", 1)
    writer.link_has_frame(anomaly_id, "rca-f2", 2)

    from graph.writer import _compute_file_id
    foo_id = _compute_file_id(repo_ref, "src/foo.py")
    bar_id = _compute_file_id(repo_ref, "src/bar.py")
    writer.link_in_file("rca-f0", foo_id)
    writer.link_in_file("rca-f1", foo_id)
    writer.link_in_file("rca-f2", bar_id)

    writer.link_touched("abc123", repo_ref, foo_id)
    writer.link_touched("abc123", repo_ref, bar_id)
    writer.link_deployed_commit("rca-deploy-001", "abc123", repo_ref)


def _all_statuses(client, anomaly_id: str) -> list[dict]:
    """Fetch all RCA_ATTRIBUTED edges with status."""
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(f:File)
    RETURN f.file_id AS file_id, f.path AS path, r.status AS status, r.run_id AS run_id
    ORDER BY f.path
    """
    return client.execute_read(q, {"anomaly_id": anomaly_id})


def main() -> None:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("NEO4J_PASSWORD required", file=sys.stderr)
        sys.exit(1)

    from graph.neo4j_client import Neo4jClient
    from graph.migrations import apply_migrations
    from graph.writer import GraphWriter
    from rca_engine import run_deterministic_rca
    from artifacts.evidence_store import LocalFileEvidenceStore
    from api.services.rca_service import get_rca_result_view, run_rca
    from api.services.feedback_service import confirm_candidate, rollback

    client = Neo4jClient(uri, user, password)
    client.connect()

    try:
        anomaly_id = "smoke-rca-api-001"
        run_id = f"smoke-rca-run-{uuid.uuid4().hex[:8]}"

        # 1. Migrations + create test anomaly
        print("1. Applying migrations and creating test anomaly...")
        apply_migrations(uri, user, password)
        writer = GraphWriter(client)
        _create_test_anomaly(client, writer, anomaly_id)
        print("   OK\n")

        # 2. Trigger deterministic RCA
        print("2. Triggering deterministic RCA...")
        evidence_dir = tempfile.mkdtemp(prefix="smoke_rca_evidence_")
        store = LocalFileEvidenceStore(evidence_dir)
        result = run_rca(
            anomaly_id,
            "manual",
            run_id=run_id,
            override=True,
            graph_client=client,
            graph_writer=writer,
            evidence_store=store,
        )
        if result is None:
            print("   BLOCKED or no candidates. Aborting.")
            sys.exit(1)
        print(f"   run_id={result['run_id']} attributions={result['attribution_count']}\n")

        # 3. Fetch results
        print("3. Fetching results...")
        view = get_rca_result_view(anomaly_id, graph_client=client)
        print(f"   current_status={view['current_status']}")
        print(f"   accepted_root_cause={view['accepted_root_cause']}")
        print(f"   candidate_root_causes={len(view['candidate_root_causes'])} items")
        for c in view["candidate_root_causes"]:
            print(f"      - {c['path']} (file_id={c['file_id'][:12]}...) status=candidate")
        print()

        candidates = view["candidate_root_causes"]
        if not candidates:
            print("   No candidates to confirm. .")
            sys.exit(1)

        # 4. Confirm one candidate
        to_confirm = candidates[0]
        file_id = to_confirm["file_id"]
        print(f"4. Confirming candidate: {to_confirm['path']} (file_id={file_id[:12]}...)")
        confirm_candidate(
            anomaly_id,
            file_id,
            run_id,
            actor_id="smoke-test",
            reason="smoke test confirm",
            graph_client=client,
        )
        print("   OK\n")

        # 5. Verify others became rejected
        print("5. Verifying others became rejected...")
        statuses = _all_statuses(client, anomaly_id)
        accepted_count = sum(1 for s in statuses if s["status"] == "accepted")
        rejected_count = sum(1 for s in statuses if s["status"] == "rejected")
        print(f"   accepted={accepted_count} rejected={rejected_count}")
        for s in statuses:
            print(f"      - {s['path']} status={s['status']}")
        if accepted_count != 1:
            print(f"   FAIL: expected 1 accepted, got {accepted_count}")
            sys.exit(1)
        if rejected_count < len(candidates) - 1:
            print(f"   FAIL: expected {len(candidates)-1} rejected, got {rejected_count}")
            sys.exit(1)
        print("   OK\n")

        # 6. Rollback
        print("6. Performing rollback...")
        rollback(anomaly_id, actor_id="smoke-test", reason="smoke test rollback", graph_client=client)
        print("   OK\n")

        # 7. Print final statuses
        print("7. Final statuses:")
        statuses = _all_statuses(client, anomaly_id)
        for s in statuses:
            print(f"   - {s['path']} status={s['status']}")
        view = get_rca_result_view(anomaly_id, graph_client=client)
        print(f"\n   current_status={view['current_status']}")
        print(f"   accepted_root_cause={view['accepted_root_cause']}")
        print(f"   candidate_root_causes={len(view['candidate_root_causes'])}")

        print("\nDone.")

    finally:
        client.close()


if __name__ == "__main__":
    main()
