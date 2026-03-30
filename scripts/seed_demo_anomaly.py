#!/usr/bin/env python3
"""
Seed Neo4j with minimal demo data for ``anomaly_001``.

**Why:** Debug-agent triage runs ``MATCH (a:Anomaly {id: $anomaly_id})``; if the
node is missing, triage reports *"Anomaly metadata not found"*. Deterministic
RCA needs stack frames linked to a file. This script seeds both.

**Connection:** Uses ``graph.neo4j_client.Neo4jClient`` (same as the app) with
``NEO4J_URI``, ``NEO4J_USER``, ``NEO4J_PASSWORD``.

**What gets seeded (minimal demo):**

- **Anomaly** ``id=anomaly_001``: ``timestamp``, ``trace_ref``, ``service_ref``,
  plus optional triage fields ``score``, ``severity``, ``message``.
- **StackFrame** ``sf_demo_anomaly_001_0``: ``trace_ref``, ``symbol_name``,
  ``resolution=resolved`` (required by pre-RCA gate / candidate generator).
- **File** (ontology hash): ``path``, ``repo_ref``, ``file_id`` — primary RCA
  candidate (``src/handlers/checkout_handler.py`` in ``demo/repo``).
- **Relationships:** ``(Anomaly)-[:HAS_FRAME {frame_order:0}]->(StackFrame)``,
  ``(StackFrame)-[:IN_FILE]->(File)``.
- **Commit / Deployment** (for signal scoring): ``Commit-[:TOUCHED]->File``,
  ``Deployment-[:DEPLOYED_COMMIT]->Commit``, deployment ``service_ref`` matches
  the anomaly.

Graph shape (RCA target is **File** via ``RCA_ATTRIBUTED`` at run time; not
written by this seed):

  Anomaly -[HAS_FRAME]-> StackFrame -[IN_FILE]-> File

Usage (from repository root)::

    export NEO4J_URI=bolt://localhost:7687
    export NEO4J_USER=neo4j
    export NEO4J_PASSWORD=your_password
    python scripts/seed_demo_anomaly.py

From a container on the Compose network, use ``bolt://neo4j:7687``; from the
host, ``bolt://localhost:7687``.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from graph.neo4j_client import Neo4jClient
from graph.writer import GraphWriter, _compute_file_id

# --- Demo constants (single anomaly, one root-cause file) ---
ANOMALY_ID = "anomaly_001"
TRACE_REF = "trace_demo_001"
SERVICE_REF = "demo-checkout-service"
REPO_REF = "demo/repo"
# Application path (must not match vendor/stdlib exclusions in candidate_generator)
FILE_PATH = "src/handlers/checkout_handler.py"
# Gate I6 / candidate_generator: frame_order on HAS_FRAME must be contiguous 0..n-1
FRAME_ID = "sf_demo_anomaly_001_0"
SYMBOL_NAME = "processPayment"
# Pre-RCA gate ``entire_trace_unresolved`` counts only resolution == "resolved" (literal)
RESOLUTION = "resolved"

COMMIT_SHA = "deadbeef0000000000000000000000000000abcd"
DEPLOYMENT_ID = "dep_demo_001"
# ISO timestamps (Anomaly / Commit); deployment uses epoch seconds string for deploy correlation queries
ANOMALY_TS = "2025-03-01T12:00:00+00:00"
COMMIT_TS = "2025-03-01T10:30:00+00:00"
# Before anomaly_ts when compared as int strings in signal_computation deploy helpers
DEPLOY_EPOCH_STR = "1740000000"


def main() -> int:
    uri = os.environ.get("NEO4J_URI", "").strip() or "bolt://localhost:7687"
    user = os.environ.get("NEO4J_USER", "").strip() or "neo4j"
    password = os.environ.get("NEO4J_PASSWORD", "")

    print("Seeding Neo4j demo graph for deterministic RCA.")
    print(f"  Anomaly id: {ANOMALY_ID}")
    print(f"  NEO4J_URI: {uri}")

    client = Neo4jClient(uri, user, password)
    client.connect()

    file_id = _compute_file_id(REPO_REF, FILE_PATH)
    writer = GraphWriter(client)

    # 1) Core RCA path: Anomaly -> HAS_FRAME -> StackFrame -> IN_FILE -> File
    writer.upsert_anomaly(ANOMALY_ID, ANOMALY_TS, trace_ref=TRACE_REF)
    writer.upsert_stackframe(
        FRAME_ID,
        TRACE_REF,
        symbol_name=SYMBOL_NAME,
        frame_order=0,
        resolution=RESOLUTION,
    )
    writer.upsert_file(FILE_PATH, REPO_REF, file_id=file_id)
    writer.link_has_frame(ANOMALY_ID, FRAME_ID, frame_order=0)
    writer.link_in_file(FRAME_ID, file_id)

    # Fields triage reads (debug_agent.triage_agent) + pre_rca_gate deployment scope
    client.execute_write(
        """
        MATCH (a:Anomaly {id: $id})
        SET a.service_ref = $service_ref,
            a.score = $score,
            a.severity = $severity,
            a.message = $message
        """,
        {
            "id": ANOMALY_ID,
            "service_ref": SERVICE_REF,
            "score": 0.85,
            "severity": "high",
            "message": "Demo: payment failure in checkout handler",
        },
    )

    # 2) Optional graph for signals: last touch + deployment (same service_ref as anomaly)
    writer.upsert_commit(COMMIT_SHA, REPO_REF, COMMIT_TS)
    writer.link_touched(COMMIT_SHA, REPO_REF, file_id)
    writer.upsert_deployment(DEPLOYMENT_ID, DEPLOY_EPOCH_STR, service_ref=SERVICE_REF)
    writer.link_deployed_commit(DEPLOYMENT_ID, COMMIT_SHA, REPO_REF)

    client.close()
    print("Done.")
    print(f"  file_id (root-cause candidate): {file_id}")
    print(f"  path: {FILE_PATH}")
    print("  Triage: MATCH (a:Anomaly {id: 'anomaly_001'}) will succeed.")
    print("  Run: GET /api/v1/rca/results/anomaly_001 or POST /debug-agent/run with anomaly_001.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Equivalent Cypher (for Neo4j Browser): scripts/cypher/seed_demo_anomaly.cypher
