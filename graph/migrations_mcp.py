"""
MCP investigation graph migrations for Neo4j.

Creates uniqueness constraints for investigation-context node identities.
Idempotent (IF NOT EXISTS).

Usage:
    from graph.migrations_mcp import apply_mcp_migrations
    apply_mcp_migrations(uri, user, password)

    # Or from env:
    python -m graph.migrations_mcp
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graph.neo4j_client import Neo4jClient


def apply_mcp_migrations(uri: str, user: str, password: str) -> None:
    """Apply MCP investigation graph constraints."""
    from graph.neo4j_client import Neo4jClient

    client = Neo4jClient(uri, user, password)
    client.connect()
    try:
        _log("Applying MCP investigation graph migrations...")
        _apply_constraints(client)
        _log("MCP migrations complete.")
    finally:
        client.close()


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _apply_constraints(client: "Neo4jClient") -> None:
    single_prop = [
        ("constraint_investigation_id", "Investigation", "id"),
        ("constraint_mcp_build_id", "Build", "id"),
        ("constraint_mcp_deployment_id", "Deployment", "id"),
        ("constraint_mcp_alert_id", "AlertEvent", "id"),
        ("constraint_pagerduty_incident_id", "PagerDutyIncident", "id"),
        ("constraint_runbook_id", "Runbook", "id"),
        ("constraint_known_issue_id", "KnownIssue", "id"),
        ("constraint_feedback_id", "Feedback", "feedback_id"),
        ("constraint_rca_candidate_id", "RCACandidate", "candidate_id"),
    ]
    for name, label, prop in single_prop:
        q = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        _log(f"  Constraint: {label}({prop})")
        client.execute_write(q)

    _log("  Constraint: Commit(sha)")
    client.execute_write(
        "CREATE CONSTRAINT constraint_mcp_commit_sha IF NOT EXISTS "
        "FOR (c:Commit) REQUIRE c.sha IS UNIQUE"
    )


if __name__ == "__main__":
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("NEO4J_PASSWORD required", file=sys.stderr)
        sys.exit(1)
    apply_mcp_migrations(uri, user, password)
