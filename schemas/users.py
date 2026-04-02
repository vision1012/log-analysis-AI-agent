"""Pydantic schemas for user management API (PostgreSQL ``users`` table)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from security.validation import normalize_and_validate_email, validate_signup_password

# Public roles accepted on create (no admin; unknown roles rejected).
ALLOWED_PUBLIC_ROLES: frozenset[str] = frozenset(
    {
        "developer",
        "support_engineer",
        "tester",
        "sre",
        "viewer",
    }
)


def validate_public_role(role: str) -> str:
    """Return normalized role or raise ValueError (for reuse in tests / services)."""
    r = role.strip()
    if not r:
        raise ValueError("role must not be empty")
    if r.lower() == "admin":
        raise ValueError('role "admin" is not permitted')
    if r not in ALLOWED_PUBLIC_ROLES:
        allowed = ", ".join(sorted(ALLOWED_PUBLIC_ROLES))
        raise ValueError(f"invalid role; allowed values: {allowed}")
    return r


class UserCreate(BaseModel):
    """Body for ``POST /api/v1/users``."""

    name: str = Field(..., min_length=1, max_length=512)
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(
        ...,
        max_length=256,
        description="Plain password; strength rules enforced in validator; stored as bcrypt hash only",
    )
    role: str = Field(
        ...,
        description="One of: developer, support_engineer, tester, sre, viewer",
    )
    team: Optional[str] = Field(None, max_length=256)
    user_id: Optional[str] = Field(
        None,
        description="Optional UUID string; generated if omitted",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return normalize_and_validate_email(v)

    @field_validator("password")
    @classmethod
    def signup_password_strength(cls, v: str) -> str:
        validate_signup_password(v)
        return v

    @field_validator("role")
    @classmethod
    def role_must_be_public(cls, v: str) -> str:
        return validate_public_role(v)

    @field_validator("user_id")
    @classmethod
    def optional_user_id_uuid(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        s = str(v).strip()
        try:
            UUID(s)
        except ValueError as e:
            raise ValueError("user_id must be a valid UUID") from e
        return s


class UserResponse(BaseModel):
    """Single user row (no password fields)."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    user_id: str
    name: str
    email: str
    role: Optional[str] = None
    team: Optional[str] = None
    created_at: datetime


class UserListResponse(BaseModel):
    """Paginated list of users."""

    users: list[UserResponse]
    total: int
    limit: int
    offset: int
