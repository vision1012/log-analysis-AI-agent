"""
Graph migrations for Neo4j schema.

Run migrations to create/update indexes and constraints.
"""

from __future__ import annotations

from typing import Any

# from graph.neo4j_client import Neo4jClient


def run_migrations(uri: str, user: str, password: str) -> None:
    """
    Apply all migrations in order.

    Args:
        uri: Neo4j connection URI.
        user: Neo4j user.
        password: Neo4j password.
    """
    # client = Neo4jClient(uri, user, password)
    # with client:
    #     _migrate_indexes(client)
    #     _migrate_constraints(client)
    pass


def _migrate_indexes(client: Any) -> None:
    """Create indexes. Idempotent (IF NOT EXISTS)."""
    pass


def _migrate_constraints(client: Any) -> None:
    """Create constraints. Idempotent (IF NOT EXISTS)."""
    pass
