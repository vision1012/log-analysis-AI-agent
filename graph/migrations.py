"""
Graph migrations for Neo4j schema.

Creates uniqueness constraints and indexes per ontology and relationships spec.
Idempotent (IF NOT EXISTS). Minimal, no frameworks.

RCA_ATTRIBUTED uniqueness (application-level; Neo4j has no relationship constraints):
- (anomaly_id, run_id): pre_rca_gate blocks when run_id already has candidates (idempotency).
- One accepted per anomaly: pre_rca_gate blocks auto-run if accepted exists; supersede_prior_attributions before write.
- writer uses supersede + write_rca_attributed in atomic batch for per-anomaly consistency.

Usage:
    from graph.migrations import apply_migrations
    apply_migrations(uri, user, password)

    # Or from env:
    python -m graph.migrations
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graph.neo4j_client import Neo4jClient


def apply_migrations(uri: str, user: str, password: str) -> None:
    """
    Apply all migrations in order.

    Creates constraints first, then indexes. Logs each step to stderr.

    Args:
        uri: Neo4j connection URI (e.g. bolt://localhost:7687).
        user: Neo4j user.
        password: Neo4j password.
    """
    from graph.neo4j_client import Neo4jClient

    client = Neo4jClient(uri, user, password)
    client.connect()
    try:
        _log("Applying Neo4j migrations...")
        _apply_constraints(client)
        _apply_indexes(client)
        _log("Migrations complete.")
    finally:
        client.close()


def run_migrations(uri: str, user: str, password: str) -> None:
    """Alias for apply_migrations."""
    apply_migrations(uri, user, password)


def _log(msg: str) -> None:
    """Write to stderr for clear log output."""
    print(msg, file=sys.stderr, flush=True)


def _apply_constraints(client: "Neo4jClient") -> None:
    """
    Create uniqueness constraints. Idempotent (IF NOT EXISTS).

    Constraints:
    - Anomaly(id)
    - StackFrame(id)
    - File(file_id)
    - Commit(sha, repo_ref) composite
    - Deployment(id)
    """
    single_prop = [
        ("constraint_anomaly_id", "Anomaly", "id"),
        ("constraint_stackframe_id", "StackFrame", "id"),
        ("constraint_file_id", "File", "file_id"),
        ("constraint_deployment_id", "Deployment", "id"),
    ]
    for name, label, prop in single_prop:
        q = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        _log(f"  Constraint: {label}({prop})")
        client.execute_write(q)

    _log("  Constraint: Commit(sha, repo_ref)")
    client.execute_write(
        "CREATE CONSTRAINT constraint_commit_sha_repo IF NOT EXISTS "
        "FOR (c:Commit) REQUIRE (c.sha, c.repo_ref) IS UNIQUE"
    )


def _apply_indexes(client: "Neo4jClient") -> None:
    """
    Create indexes for timestamp and lookup fields. Idempotent (IF NOT EXISTS).

    Indexes:
    - Anomaly(timestamp)
    - Commit(timestamp)
    - Deployment(timestamp)
    - StackFrame(trace_ref)
    """
    indexes = [
        ("index_anomaly_timestamp", "Anomaly", "timestamp"),
        ("index_commit_timestamp", "Commit", "timestamp"),
        ("index_deployment_timestamp", "Deployment", "timestamp"),
        ("index_stackframe_trace_ref", "StackFrame", "trace_ref"),
    ]
    for name, label, prop in indexes:
        q = f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
        _log(f"  Index: {label}({prop})")
        client.execute_write(q)


if __name__ == "__main__":
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("NEO4J_PASSWORD required", file=sys.stderr)
        sys.exit(1)
    apply_migrations(uri, user, password)
