"""
Graph migrations for Neo4j schema.

Creates uniqueness constraints and indexes per ontology and relationships spec.
Idempotent (IF NOT EXISTS). Minimal, no frameworks.

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

    Per ontology/relationships:
    - Anomaly.id
    - StackFrame.id
    - File: (path, repo_ref) — path+repo_ref more stable than id across repos
    - Commit: (sha, repo_ref)
    - Deployment.id
    """
    constraints = [
        ("constraint_anomaly_id", "Anomaly", "id"),
        ("constraint_stackframe_id", "StackFrame", "id"),
        ("constraint_deployment_id", "Deployment", "id"),
    ]

    for name, label, prop in constraints:
        q = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        _log(f"  Constraint: {label}({prop})")
        client.execute_write(q)

    # Composite: File (path, repo_ref)
    _log("  Constraint: File(path, repo_ref)")
    client.execute_write(
        "CREATE CONSTRAINT constraint_file_path_repo IF NOT EXISTS "
        "FOR (f:File) REQUIRE (f.path, f.repo_ref) IS UNIQUE"
    )

    # Composite: Commit (sha, repo_ref)
    _log("  Constraint: Commit(sha, repo_ref)")
    client.execute_write(
        "CREATE CONSTRAINT constraint_commit_sha_repo IF NOT EXISTS "
        "FOR (c:Commit) REQUIRE (c.sha, c.repo_ref) IS UNIQUE"
    )


def _apply_indexes(client: "Neo4jClient") -> None:
    """
    Create indexes for timestamp and lookup fields. Idempotent (IF NOT EXISTS).

    Timestamp indexes support time-range queries (I12, I13, I15, deployment timing).
    """
    indexes = [
        ("index_anomaly_timestamp", "Anomaly", "timestamp"),
        ("index_anomaly_window_id", "Anomaly", "window_id"),
        ("index_anomaly_trace_ref", "Anomaly", "trace_ref"),
        ("index_stackframe_trace_ref", "StackFrame", "trace_ref"),
        ("index_commit_timestamp", "Commit", "timestamp"),
        ("index_commit_repo_ref", "Commit", "repo_ref"),
        ("index_deployment_timestamp", "Deployment", "timestamp"),
        ("index_deployment_service_ref", "Deployment", "service_ref"),
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
