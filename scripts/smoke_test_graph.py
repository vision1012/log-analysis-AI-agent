#!/usr/bin/env python3
"""
Smoke test for graph layer: migrations, write, post-ingestion gate, RCA.

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=xxx python scripts/smoke_test_graph.py

Requires: neo4j driver (pip install neo4j)
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Suppress verbose logging
import logging
logging.getLogger("graph").setLevel(logging.WARNING)
logging.getLogger("gates").setLevel(logging.WARNING)
logging.getLogger("rca_engine").setLevel(logging.WARNING)


def main() -> None:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("NEO4J_PASSWORD required", file=sys.stderr)
        sys.exit(1)

    from graph.neo4j_client import Neo4jClient
    from graph.migrations import apply_migrations
    from graph.writer import GraphWriter, _compute_file_id
    from gates.post_ingestion_gate import run_post_ingestion_gate
    from rca_engine import run_deterministic_rca
    from artifacts.evidence_store import LocalFileEvidenceStore

    client = Neo4jClient(uri, user, password)
    client.connect()

    try:
        # 1. Apply migrations
        print("1. Applying migrations...")
        apply_migrations(uri, user, password)
        print("   OK\n")

        writer = GraphWriter(client)

        # 2. Insert anomaly + trace
        anomaly_id = "smoke-anomaly-001"
        trace_ref = "a1b2c3d4e5f6"
        repo_ref = "smoke-repo"
        service_ref = "smoke-service"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        print("2. Inserting anomaly + trace...")
        writer.upsert_anomaly(anomaly_id, ts, trace_ref=trace_ref, window_id="smoke-w1")
        client.execute_write(
            "MATCH (a:Anomaly {id: $id}) SET a.service_ref = $service_ref",
            {"id": anomaly_id, "service_ref": service_ref},
        )
        writer.upsert_stackframe("smoke-frame-0", trace_ref, symbol_name="main", frame_order=0, resolution="resolved")
        writer.upsert_stackframe("smoke-frame-1", trace_ref, symbol_name="handle_request", frame_order=1, resolution="resolved")
        writer.upsert_stackframe("smoke-frame-2", trace_ref, symbol_name="process", frame_order=2, resolution="resolved")

        writer.upsert_file("src/foo.py", repo_ref)
        writer.upsert_file("src/bar.py", repo_ref)
        writer.upsert_commit("abc123def456", repo_ref, ts)
        writer.upsert_deployment("smoke-deploy-001", ts, service_ref=service_ref)
        print("   OK\n")

        # 3. Link relationships
        print("3. Linking relationships...")
        writer.link_has_frame(anomaly_id, "smoke-frame-0", 0)
        writer.link_has_frame(anomaly_id, "smoke-frame-1", 1)
        writer.link_has_frame(anomaly_id, "smoke-frame-2", 2)

        foo_id = _compute_file_id(repo_ref, "src/foo.py")
        bar_id = _compute_file_id(repo_ref, "src/bar.py")
        writer.link_in_file("smoke-frame-0", foo_id)
        writer.link_in_file("smoke-frame-1", foo_id)
        writer.link_in_file("smoke-frame-2", bar_id)

        writer.link_touched("abc123def456", repo_ref, foo_id)
        writer.link_touched("abc123def456", repo_ref, bar_id)

        writer.link_deployed_commit("smoke-deploy-001", "abc123def456", repo_ref)
        print("   OK\n")

        # 4. Post-ingestion gate
        print("4. Post-ingestion gate...")
        post_result = run_post_ingestion_gate(client, anomaly_id, batch_id="smoke-batch")
        print(f"   Result: {post_result.result.value}")
        for r in post_result.reasons:
            print(f"   - {r}")
        print()

        # 5. Run deterministic RCA
        print("5. Running run_deterministic_rca(anomaly_id)...")
        evidence_dir = tempfile.mkdtemp(prefix="smoke_evidence_")
        store = LocalFileEvidenceStore(evidence_dir)

        result = run_deterministic_rca(
            anomaly_id,
            "manual",
            graph_client=client,
            graph_writer=writer,
            evidence_store=store,
            run_id="smoke-run-001",
        )

        if result is None:
            print("   BLOCKED or no candidates\n")
        else:
            print(f"   run_id: {result.run_id}")
            print(f"   attributions: {result.attribution_count}")
            print(f"   bundles: {result.bundle_ids}")
            print("   OK\n")

        # 6. Print produced candidate files and scores
        print("6. RCA_ATTRIBUTED candidates (from graph):")
        q = """
        MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(f:File)
        WHERE r.status = 'candidate'
        RETURN f.file_id AS file_id, f.path AS path,
               r.confidence AS confidence, r.run_id AS run_id, r.evidence_ref AS evidence_ref
        ORDER BY r.confidence DESC
        """
        rows = client.execute_read(q, {"anomaly_id": anomaly_id})
        if not rows:
            print("   (none)")
        else:
            for i, row in enumerate(rows, 1):
                print(f"   {i}. {row['path']} (file_id={row['file_id'][:12]}...)")
                ev = str(row.get("evidence_ref", ""))
                print(f"      confidence={row['confidence']:.3f}  run_id={row['run_id']}  evidence_ref={ev[:16]}...")
        print()

        # 7. Verify RCA_ATTRIBUTED edges exist
        print("7. Verification:")
        count = len(rows)
        if result and result.attribution_count > 0:
            assert count == result.attribution_count, f"Expected {result.attribution_count} edges, got {count}"
            print(f"   RCA_ATTRIBUTED edges: {count} (OK)")
        else:
            print(f"   RCA_ATTRIBUTED edges: {count}")
        print()

        print("Done.")

    finally:
        client.close()


if __name__ == "__main__":
    main()
