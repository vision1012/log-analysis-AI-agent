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
        UserCreate(
            first_name="A",
            last_name="",
            email="a@b.co",
            password="Valid1!Pass",
            role="admin",
        )


def test_user_create_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            first_name="A",
            last_name="",
            email="a@b.co",
            password="short",
            role="developer",
        )


def test_user_create_accepts_valid_payload() -> None:
    u = UserCreate(
        first_name="Ada",
        last_name="Lovelace",
        email="Ada@Example.com",
        password="Securepw1!",
        role="developer",
        team="Core",
    )
    assert u.email == "ada@example.com"
    assert u.role == "developer"


def test_user_create_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError) as exc:
        UserCreate(
            first_name="A",
            last_name="",
            email="not-an-email",
            password="Securepw1!",
            role="developer",
        )
    assert any("invalid email format" in str(e.get("msg", "")).lower() for e in exc.value.errors())


def test_user_create_rejects_password_missing_character_types() -> None:
    with pytest.raises(ValidationError) as exc:
        UserCreate(
            first_name="A",
            last_name="",
            email="a@b.co",
            password="onlylowerletters",
            role="developer",
        )
    msgs = " ".join(str(e.get("msg", "")) for e in exc.value.errors())
    assert "password missing required character types" in msgs.lower()


def test_user_create_optional_user_id() -> None:
    u = UserCreate(
        first_name="Ada",
        last_name="",
        email="ada@example.com",
        password="Securepw1!",
        role="viewer",
        user_id="123e4567-e89b-12d3-a456-426614174000",
    )
    assert u.user_id == "123e4567-e89b-12d3-a456-426614174000"


def test_user_create_invalid_uuid() -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            first_name="A",
            last_name="",
            email="a@b.co",
            password="Valid1!Pass",
            role="sre",
            user_id="not-a-uuid",
        )
