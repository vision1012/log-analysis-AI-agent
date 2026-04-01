"""Repository functions for ``User`` rows."""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional, Sequence, Union

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.postgres.models import User

_USER_FIELDS = frozenset({"user_id", "name", "email", "password_hash", "role", "team"})


class DuplicateUserEmailError(Exception):
    """Insert failed: email already exists (unique constraint)."""

    def __init__(self, email: str) -> None:
        self.email = email
        super().__init__(f"user email already exists: {email!r}")


def _normalize_user_id(user_id: Union[str, uuid.UUID]) -> str:
    if isinstance(user_id, uuid.UUID):
        return str(user_id)
    s = str(user_id).strip()
    if not s:
        raise ValueError("user_id must be non-empty")
    return s


def create_user(session: Session, user_data: Mapping[str, Any]) -> User:
    """Insert a user. Unknown keys are ignored. ``user_id`` is generated if omitted."""
    data = {k: v for k, v in user_data.items() if k in _USER_FIELDS}
    if "user_id" not in data or data["user_id"] is None:
        data["user_id"] = str(uuid.uuid4())
    else:
        data["user_id"] = _normalize_user_id(data["user_id"])
    user = User(**data)
    session.add(user)
    try:
        session.flush()
    except IntegrityError as e:
        err = str(getattr(e, "orig", e) or e).lower()
        if "email" in err or "users_email" in err:
            raise DuplicateUserEmailError(data.get("email", "")) from e
        raise
    return user


def get_user_by_id(session: Session, user_id: Union[str, uuid.UUID]) -> Optional[User]:
    uid = _normalize_user_id(user_id)
    return session.get(User, uid)


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    normalized = email.strip().lower()
    stmt = select(User).where(func.lower(User.email) == normalized).limit(1)
    return session.scalars(stmt).first()


def list_users(session: Session, limit: int = 50, offset: int = 0) -> Sequence[User]:
    stmt = (
        select(User)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return session.scalars(stmt).all()


def count_users(session: Session) -> int:
    """Return total row count in ``users`` (for pagination metadata)."""
    n = session.scalar(select(func.count()).select_from(User))
    return int(n or 0)
