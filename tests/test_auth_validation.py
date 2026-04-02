"""Login request validation: email format only; no signup password strength rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.auth import LoginRequest


def test_login_accepts_weak_password() -> None:
    """Login must not enforce signup complexity (legacy/simple passwords still verify server-side)."""
    r = LoginRequest(email="user@example.com", password="a")
    assert r.password == "a"


def test_login_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError) as exc:
        LoginRequest(email="not-an-email", password="x")
    errs = exc.value.errors()
    assert any("invalid email format" in str(e.get("msg", "")).lower() for e in errs)
