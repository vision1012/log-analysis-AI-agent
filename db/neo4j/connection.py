"""
Neo4j driver from ``NEO4J_URI``, ``NEO4J_USER``, ``NEO4J_PASSWORD``.

Uses the official ``neo4j`` Python driver (``GraphDatabase.driver``).
"""

from __future__ import annotations

import os
from typing import Optional

from neo4j import Driver, GraphDatabase

_driver: Optional[Driver] = None


def get_neo4j_uri() -> str:
    uri = os.environ.get("NEO4J_URI")
    if not uri or not uri.strip():
        raise ValueError("NEO4J_URI environment variable is required and must be non-empty")
    return uri.strip()


def get_neo4j_user() -> str:
    user = os.environ.get("NEO4J_USER")
    if user is None or not str(user).strip():
        raise ValueError("NEO4J_USER environment variable is required and must be non-empty")
    return str(user).strip()


def get_neo4j_password() -> str:
    """Password may be empty for some local/dev setups."""
    return os.environ.get("NEO4J_PASSWORD", "")


def get_driver() -> Driver:
    """Return a singleton :class:`neo4j.Driver` (lazy-initialized)."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            get_neo4j_uri(),
            auth=(get_neo4j_user(), get_neo4j_password()),
            max_connection_lifetime=3600,
        )
    return _driver


def close_driver() -> None:
    """Close the singleton driver (e.g. app shutdown)."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
