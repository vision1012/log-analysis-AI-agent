#!/usr/bin/env python3
"""
Local smoke test for GraphRAG explanation layer.

Steps:
1) create/reuse sample anomaly with deterministic RCA candidates
2) run explanation generator
3) print primary candidate, summary, evidence highlights, patch direction
4) verify output validator passes

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=xxx \
      python scripts/smoke_test_graphrag.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _require_password() -> str:
    pwd = os.environ.get("NEO4J_PASSWORD", "")
    if not pwd:
        print("NEO4J_PASSWORD required", file=sys.stderr)
        sys.exit(1)
    return pwd


def _has_candidates(client, anomaly_id: str) -> bool:
    q = """
    MATCH (:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->()
    WHERE r.status IN ['candidate', 'accepted']
    RETURN count(r) AS n
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return bool(rows and rows[0].get("n", 0) > 0)


def _latest_run_id(client, anomaly_id: str) -> str:
    q = """
    MATCH (:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->()
    WHERE r.status IN ['candidate', 'accepted']
    RETURN r.run_id AS run_id, coalesce(r.created_at, '') AS ts
    ORDER BY ts DESC
    LIMIT 1
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return (rows[0].get("run_id") if rows else "") or ""


def _seed_and_run_deterministic(anomaly_id: str, client, evidence_store) -> str:
    from graph.writer import GraphWriter, _compute_file_id
    from rca_engine import run_deterministic_rca

    writer = GraphWriter(client)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trace_ref = "graphrag-trace-001"
    repo_ref = "graphrag-smoke-repo"
    service_ref = "graphrag-smoke-service"

    writer.upsert_anomaly(anomaly_id, now, trace_ref=trace_ref, window_id="graphrag-smoke-window")
    client.execute_write(
        "MATCH (a:Anomaly {id: $id}) SET a.service_ref = $service_ref",
        {"id": anomaly_id, "service_ref": service_ref},
    )

    writer.upsert_stackframe("graphrag-frame-0", trace_ref, symbol_name="main", frame_order=0, resolution="resolved")
    writer.upsert_stackframe("graphrag-frame-1", trace_ref, symbol_name="handler", frame_order=1, resolution="resolved")
    writer.upsert_stackframe("graphrag-frame-2", trace_ref, symbol_name="process", frame_order=2, resolution="resolved")

    writer.link_has_frame(anomaly_id, "graphrag-frame-0", 0)
    writer.link_has_frame(anomaly_id, "graphrag-frame-1", 1)
    writer.link_has_frame(anomaly_id, "graphrag-frame-2", 2)

    writer.upsert_file("src/graphrag/foo.py", repo_ref)
    writer.upsert_file("src/graphrag/bar.py", repo_ref)
    foo_id = _compute_file_id(repo_ref, "src/graphrag/foo.py")
    bar_id = _compute_file_id(repo_ref, "src/graphrag/bar.py")
    writer.link_in_file("graphrag-frame-0", foo_id)
    writer.link_in_file("graphrag-frame-1", foo_id)
    writer.link_in_file("graphrag-frame-2", bar_id)

    commit_sha = "graphragabc123def456"
    deploy_id = "graphrag-deploy-001"
    writer.upsert_commit(commit_sha, repo_ref, now)
    writer.upsert_deployment(deploy_id, now, service_ref=service_ref)
    writer.link_touched(commit_sha, repo_ref, foo_id)
    writer.link_touched(commit_sha, repo_ref, bar_id)
    writer.link_deployed_commit(deploy_id, commit_sha, repo_ref)

    run_id = f"graphrag-smoke-run-{int(datetime.now(timezone.utc).timestamp())}"

    result = run_deterministic_rca(
        anomaly_id,
        "manual",
        graph_client=client,
        graph_writer=writer,
        evidence_store=evidence_store,
        run_id=run_id,
    )
    if result is None:
        raise RuntimeError("Deterministic RCA did not produce candidates for smoke anomaly.")
    return result.run_id


def main() -> None:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = _require_password()
    anomaly_id = os.environ.get("SMOKE_GRAPHRAG_ANOMALY_ID", "smoke-graphrag-anomaly-001")

    from artifacts.evidence_store import LocalFileEvidenceStore
    from graph.migrations import apply_migrations
    from graph.neo4j_client import Neo4jClient
    from graphrag.context_packer import pack_context
    from graphrag.explanation_generator import generate_explanation
    from graphrag.llm_client import GraphRAGLLMClient, LLMConfig
    from graphrag.output_validator import validate_output

    apply_migrations(uri, user, password)
    client = Neo4jClient(uri, user, password)
    client.connect()

    evidence_base = os.environ.get("EVIDENCE_STORE_DIR") or tempfile.gettempdir()
    store = LocalFileEvidenceStore(os.path.join(evidence_base, "evidence_bundles"))

    try:
        if _has_candidates(client, anomaly_id):
            run_id = _latest_run_id(client, anomaly_id)
            print(f"[reuse] using existing anomaly={anomaly_id} run_id={run_id or 'latest'}")
        else:
            run_id = _seed_and_run_deterministic(anomaly_id, client, store)
            print(f"[seeded] anomaly={anomaly_id} run_id={run_id}")

        # For smoke/local usage, default to stub unless env overrides provider.
        llm_cfg = LLMConfig.from_env()
        llm = GraphRAGLLMClient(llm_cfg)

        explanation = generate_explanation(
            anomaly_id,
            graph_client=client,
            evidence_store=store,
            llm_client=llm,
            run_id=run_id or None,
        )

        print("\n=== GraphRAG Explanation ===")
        print(f"anomaly_id: {explanation.get('anomaly_id')}")
        primary = explanation.get("primary_candidate") or {}
        print(f"primary candidate: {primary.get('path') or primary.get('file_id')}")
        print("ranked hypotheses:")
        for h in (explanation.get("ranked_hypotheses") or []):
            if isinstance(h, dict):
                print(f" - rank {h.get('rank')}: {h.get('path') or h.get('file_id')} (conf={h.get('confidence')})")
        print(f"explanation summary: {explanation.get('explanation_summary')}")
        print("evidence highlights:")
        for item in (explanation.get("evidence_highlights") or []):
            print(f" - {item}")
        print(f"optional patch direction: {explanation.get('optional_patch_direction')}")

        context_pack = pack_context(
            anomaly_id,
            graph_client=client,
            evidence_store=store,
            run_id=run_id or None,
        )
        ok, errors = validate_output(explanation, context_pack=context_pack)
        print(f"\nvalidator pass: {ok}")
        if not ok:
            print("validator errors:")
            for e in errors:
                print(f" - {e}")
            sys.exit(2)

        print("\nGRAPHRAG_SLICE4_COMPLETE")
    finally:
        client.close()


if __name__ == "__main__":
    main()
