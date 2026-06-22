"""Ensure repo root is on ``sys.path`` so ``pytest`` works without ``PYTHONPATH``."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("DISABLE_LLM", "true")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")


@pytest.fixture(autouse=True)
def _auth_dependency_override():
    """Allow route tests to hit protected endpoints without a live Postgres user row."""
    from api.deps.auth import get_current_user
    from api.main import app
    from schemas.users import UserResponse

    async def _test_user() -> UserResponse:
        return UserResponse(
            user_id="00000000-0000-0000-0000-000000000001",
            first_name="Test",
            last_name="User",
            email="test@example.com",
            is_email_verified=True,
            role="developer",
            team=None,
            created_at=datetime(2020, 1, 1, 0, 0, 0),
        )

    app.dependency_overrides[get_current_user] = _test_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
