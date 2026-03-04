"""
Neo4j client for RCA graph operations.

Connects to Neo4j via NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
Requires: pip install neo4j
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None  # type: ignore[misc, assignment]


class Neo4jClient:
    """Minimal Neo4j client. execute_read/execute_write for graph operations."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        *,
        max_connection_lifetime: int = 3600,
    ) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._max_connection_lifetime = max_connection_lifetime
        self._driver: Any = None

    def connect(self) -> None:
        """Open connection. Call before use."""
        if GraphDatabase is None:
            raise ImportError("neo4j package required. Install with: pip install neo4j")
        self._driver = GraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
            max_connection_lifetime=self._max_connection_lifetime,
        )

    def close(self) -> None:
        """Close connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    def execute_read(self, query: str, parameters: Optional[dict] = None) -> list[dict]:
        """Execute read-only Cypher query. Returns list of records as dicts."""
        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [dict(r) for r in result]

    def execute_write(self, query: str, parameters: Optional[dict] = None) -> None:
        """Execute write Cypher query."""
        with self._driver.session() as session:
            session.run(query, parameters or {})

    def execute_write_tx(
        self, operations: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Execute multiple write queries in one atomic transaction."""
        with self._driver.session() as session:
            with session.begin_transaction() as tx:
                for query, params in operations:
                    tx.run(query, params)

    def __enter__(self) -> "Neo4jClient":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
