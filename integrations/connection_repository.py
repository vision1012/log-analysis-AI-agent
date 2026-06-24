"""Repository functions for ``integration_connections`` rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.postgres.models import IntegrationConnection

_CONNECTION_FIELDS = frozenset(
    {
        "id",
        "workspace_id",
        "provider",
        "display_name",
        "base_url",
        "org_name",
        "project_key",
        "repo_name",
        "config_json",
        "encrypted_credentials",
        "is_enabled",
        "created_by",
        "created_at",
        "updated_at",
        "last_validated_at",
        "last_validation_status",
        "last_validation_error",
    }
)


class IntegrationConnectionNotFoundError(Exception):
    """Raised when a connection id does not exist."""


def _normalize_id(connection_id: str) -> str:
    value = str(connection_id or "").strip()
    if not value:
        raise ValueError("connection_id must be non-empty")
    return value


def create_connection(session: Session, data: Mapping[str, Any]) -> IntegrationConnection:
    payload = {k: v for k, v in data.items() if k in _CONNECTION_FIELDS}
    if "id" not in payload or not payload["id"]:
        payload["id"] = str(uuid.uuid4())
    else:
        payload["id"] = _normalize_id(payload["id"])
    if payload.get("config_json") is None:
        payload["config_json"] = {}
    row = IntegrationConnection(**payload)
    session.add(row)
    session.flush()
    return row


def list_connections(session: Session, workspace_id: str) -> Sequence[IntegrationConnection]:
    stmt = (
        select(IntegrationConnection)
        .where(IntegrationConnection.workspace_id == workspace_id.strip())
        .order_by(IntegrationConnection.created_at.desc())
    )
    return session.scalars(stmt).all()


def get_connection(session: Session, connection_id: str) -> Optional[IntegrationConnection]:
    return session.get(IntegrationConnection, _normalize_id(connection_id))


def get_enabled_connection(
    session: Session,
    *,
    workspace_id: str,
    provider: str,
    repo_name: str | None = None,
) -> Optional[IntegrationConnection]:
    provider_norm = provider.strip().lower()
    stmt = (
        select(IntegrationConnection)
        .where(
            IntegrationConnection.workspace_id == workspace_id.strip(),
            IntegrationConnection.provider == provider_norm,
            IntegrationConnection.is_enabled.is_(True),
        )
        .order_by(IntegrationConnection.updated_at.desc())
    )
    rows = session.scalars(stmt).all()
    if not rows:
        return None
    if repo_name:
        repo = repo_name.strip().lower()
        for row in rows:
            if (row.repo_name or "").strip().lower() == repo:
                return row
    return rows[0]


def update_connection(
    session: Session,
    connection_id: str,
    updates: Mapping[str, Any],
) -> IntegrationConnection:
    row = get_connection(session, connection_id)
    if row is None:
        raise IntegrationConnectionNotFoundError(connection_id)
    for key, value in updates.items():
        if key not in _CONNECTION_FIELDS or key in {"id", "created_at", "created_by"}:
            continue
        setattr(row, key, value)
    row.updated_at = datetime.utcnow()
    session.flush()
    return row


def delete_connection(session: Session, connection_id: str) -> None:
    row = get_connection(session, connection_id)
    if row is None:
        raise IntegrationConnectionNotFoundError(connection_id)
    session.delete(row)
    session.flush()


def update_validation_status(
    session: Session,
    connection_id: str,
    *,
    status: str,
    error: str | None = None,
    validated_at: datetime | None = None,
) -> IntegrationConnection:
    row = get_connection(session, connection_id)
    if row is None:
        raise IntegrationConnectionNotFoundError(connection_id)
    row.last_validation_status = status
    row.last_validation_error = error
    row.last_validated_at = validated_at or datetime.utcnow()
    row.updated_at = datetime.utcnow()
    session.flush()
    return row


def count_connections(session: Session, workspace_id: str) -> int:
    n = session.scalar(
        select(func.count())
        .select_from(IntegrationConnection)
        .where(IntegrationConnection.workspace_id == workspace_id.strip())
    )
    return int(n or 0)
