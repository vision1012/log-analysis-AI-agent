"""Login enforces email verification (verified-only access)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.users_service import EmailNotVerifiedError, login_svc
from schemas.auth import LoginRequest


def test_login_svc_raises_when_email_not_verified() -> None:
    row = MagicMock()
    row.password_hash = "stored-hash"
    row.is_email_verified = False
    row.email = "user@example.com"

    with (
        patch("api.services.users_service.get_user_by_email", return_value=row),
        patch("api.services.users_service.verify_password", return_value=True),
    ):
        with pytest.raises(EmailNotVerifiedError) as exc:
            login_svc(LoginRequest(email="user@example.com", password="correct"))
        assert exc.value.email == "user@example.com"


def test_login_endpoint_403_json_shape_for_unverified() -> None:
    with patch("api.routers.auth_routes.login_svc") as mock_login:
        mock_login.side_effect = EmailNotVerifiedError(email="u@example.com")
        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "u@example.com", "password": "password!"},
        )
    assert r.status_code == 403
    data = r.json()
    assert data["detail"]["code"] == "email_not_verified"
    assert data["detail"]["message"] == "verify your email before logging in"
    assert data["detail"]["email"] == "u@example.com"


def test_login_svc_succeeds_when_verified() -> None:
    from datetime import datetime

    from schemas.users import UserResponse

    row = MagicMock()
    row.password_hash = "stored-hash"
    row.is_email_verified = True
    row.user_id = "uid-1"
    row.first_name = "A"
    row.last_name = "B"
    row.email = "user@example.com"
    row.role = "developer"
    row.team = None
    row.created_at = datetime(2020, 1, 1, 0, 0, 0)

    with (
        patch("api.services.users_service.get_user_by_email", return_value=row),
        patch("api.services.users_service.verify_password", return_value=True),
    ):
        out = login_svc(LoginRequest(email="user@example.com", password="correct"))
    assert isinstance(out, UserResponse)
    assert out.email == "user@example.com"
