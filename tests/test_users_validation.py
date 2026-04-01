"""Unit tests for user role validation (no database required)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.users import UserCreate, validate_public_role


def test_validate_public_role_accepts_allowed() -> None:
    for r in ("developer", "support_engineer", "tester", "sre", "viewer"):
        assert validate_public_role(r) == r
        assert validate_public_role(f"  {r}  ") == r


def test_validate_public_role_rejects_admin() -> None:
    with pytest.raises(ValueError, match="admin"):
        validate_public_role("admin")


def test_validate_public_role_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="invalid role"):
        validate_public_role("superuser")


def test_user_create_rejects_wrong_role() -> None:
    with pytest.raises(ValidationError):
        UserCreate(name="A", email="a@b.co", role="admin")


def test_user_create_accepts_valid_payload() -> None:
    u = UserCreate(name="Ada", email="Ada@Example.com", role="developer", team="Core")
    assert u.email == "ada@example.com"
    assert u.role == "developer"


def test_user_create_optional_user_id() -> None:
    u = UserCreate(
        name="Ada",
        email="ada@example.com",
        role="viewer",
        user_id="123e4567-e89b-12d3-a456-426614174000",
    )
    assert u.user_id == "123e4567-e89b-12d3-a456-426614174000"


def test_user_create_invalid_uuid() -> None:
    with pytest.raises(ValidationError):
        UserCreate(name="A", email="a@b.co", role="sre", user_id="not-a-uuid")
