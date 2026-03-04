#!/usr/bin/env python3
"""
Smoke test for graph layer: migrations, write, post-ingestion gate, pre-RCA gate.

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=xxx python scripts/smoke_test_graph.py

Requires: neo4j driver (pip install neo4j)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Suppress verbose logging
import logging
logging.getLogger("graph").setLevel(logging.WARNING)
logging.getLogger("gates").setLevel(logging.WARNING)


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
    from gates.post_ingestion_gate import run_post_ingestion_gate
    from gates.pre_rca_gate import run_pre_rca_gate

    client = Neo4jClient(uri, user, password)
    client.connect()

    try:
        # 1. Apply migrations
        print("1. Applying migrations...")
        apply_migrations(uri, user, password)
        print("   OK\n")

        writer = GraphWriter(client)

        # 2. Insert fake data
        anomaly_id = "smoke-anomaly-001"
        trace_ref = "a1b2c3d4e5f6"
        repo_ref = "smoke-repo"
        service_ref = "smoke-service"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        print("2. Inserting nodes...")
        writer.upsert_anomaly(anomaly_id, ts, trace_ref=trace_ref, window_id="smoke-w1")
        client.execute_write(
            "MATCH (a:Anomaly {id: $id}) SET a.service_ref = $service_ref",
            {"id": anomaly_id, "service_ref": service_ref},
        )
        writer.upsert_stackframe("smoke-frame-0", trace_ref, symbol_name="main", frame_order=0)
        writer.upsert_stackframe("smoke-frame-1", trace_ref, symbol_name="handle_request", frame_order=1)
        writer.upsert_stackframe("smoke-frame-2", trace_ref, symbol_name="process", frame_order=2)

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

        writer.link_in_file("smoke-frame-0", f"{repo_ref}:src/foo.py")
        writer.link_in_file("smoke-frame-1", f"{repo_ref}:src/foo.py")
        writer.link_in_file("smoke-frame-2", f"{repo_ref}:src/bar.py")

        writer.link_touched("abc123def456", repo_ref, f"{repo_ref}:src/foo.py")
        writer.link_touched("abc123def456", repo_ref, f"{repo_ref}:src/bar.py")

        writer.link_deployed_commit("smoke-deploy-001", "abc123def456", repo_ref)
        print("   OK\n")

        # 4. Run gates
        print("4. Post-ingestion gate...")
        post_result = run_post_ingestion_gate(client, anomaly_id, batch_id="smoke-batch")
        print(f"   Result: {post_result.result.value}")
        for r in post_result.reasons:
            print(f"   - {r}")
        print()

        print("5. Pre-RCA gate...")
        pre_result = run_pre_rca_gate(client, anomaly_id, run_id="smoke-run-001", trigger="auto")
        print(f"   Result: {pre_result.result.value}")
        for r in pre_result.reasons:
            print(f"   - {r}")
        print()

        print("Done.")

    finally:
        client.close()


if __name__ == "__main__":
    main()
