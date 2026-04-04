"""Pydantic schemas for user management API (PostgreSQL ``users`` table).

Signup and user creation use ``first_name`` and ``last_name`` separately (no combined ``name`` field).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
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
    """Body for ``POST /api/v1/users`` (signup).

    Uses ``first_name`` and ``last_name`` only. There is **no** ``name`` field (OpenAPI/FastAPI must not require it).
    """

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "email": "ada@example.com",
                    "password": "Securepw1!",
                    "role": "developer",
                    "team": "Core",
                }
            ]
        },
    )

    first_name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Given name (required)",
    )
    last_name: str = Field(
        ...,
        min_length=0,
        max_length=256,
        description="Family name; may be empty string if only one name is provided",
    )
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(
        ...,
        max_length=256,
        description="Plain password; strength rules enforced in validator; stored as bcrypt hash only",
    )
    role: Optional[str] = Field(
        None,
        description="One of: developer, support_engineer, tester, sre, viewer (omit for null)",
    )
    team: Optional[str] = Field(None, max_length=256)
    user_id: Optional[str] = Field(
        None,
        description="Optional UUID string; generated if omitted",
    )

    @field_validator("first_name", mode="before")
    @classmethod
    def first_name_strip(cls, v: Any) -> str:
        if v is None:
            raise ValueError("first_name is required")
        s = str(v).strip()
        if not s:
            raise ValueError("first_name must not be empty")
        return s

    @field_validator("last_name", mode="before")
    @classmethod
    def last_name_strip(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()

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
    def role_must_be_public(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return validate_public_role(s)

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
    """Single user row: identity fields only (no password, hash, or tokens)."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    user_id: str
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool = False
    role: Optional[str] = None
    team: Optional[str] = None
    created_at: datetime


class UserListResponse(BaseModel):
    """Paginated list of users."""

    users: list[UserResponse]
    total: int
    limit: int
    offset: int
