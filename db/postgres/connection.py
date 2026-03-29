"""
PostgreSQL connection: engine and session factory from ``POSTGRES_URL``.

Works with any standard PostgreSQL connection string (including Supabase).
"""

# NOTE:
# Database schema is managed via SQL files (schema.sql)
# SQLAlchemy is used only for querying

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None


def get_postgres_url() -> str:
    url = os.environ.get("POSTGRES_URL")
    if not url or not url.strip():
        raise ValueError("POSTGRES_URL environment variable is required and must be non-empty")
    return url.strip()


def get_engine() -> Engine:
    """Return a singleton SQLAlchemy engine (lazy-initialized)."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_postgres_url(),
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return a singleton session factory bound to :func:`get_engine`."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal


def get_session() -> Session:
    """Open a new ORM :class:`~sqlalchemy.orm.Session` (caller manages lifecycle)."""
    return get_session_factory()()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager that yields a session, commits on success, rolls back on error, and closes.
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_db_session_readonly() -> Generator[Session, None, None]:
    """
    Read-only use: no commit. Rolls back and closes so read paths do not open write transactions.
    """
    session = get_session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
