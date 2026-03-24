"""Repository functions for ``User`` rows."""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.postgres.models import User

_USER_FIELDS = frozenset({"user_id", "name", "email", "role", "team"})


def create_user(session: Session, user_data: Mapping[str, Any]) -> User:
    """Insert a user. Unknown keys are ignored. ``user_id`` is generated if omitted."""
    data = {k: v for k, v in user_data.items() if k in _USER_FIELDS}
    if "user_id" not in data or data["user_id"] is None:
        data["user_id"] = uuid.uuid4()
    user = User(**data)
    session.add(user)
    session.flush()
    return user


def get_user_by_id(session: Session, user_id: uuid.UUID) -> Optional[User]:
    return session.get(User, user_id)


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    stmt = select(User).where(User.email == email).limit(1)
    return session.scalars(stmt).first()


def list_users(session: Session, limit: int = 50, offset: int = 0) -> Sequence[User]:
    stmt = (
        select(User)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return session.scalars(stmt).all()
