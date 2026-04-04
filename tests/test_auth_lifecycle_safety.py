"""Auth lifecycle: email send failures must not break API contracts."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from api.services.auth_lifecycle import forgot_password_request


def test_forgot_password_send_failure_does_not_propagate() -> None:
    """Resend (or any) failure is caught; caller still returns generic success to HTTP layer."""
    user = MagicMock()
    user.email = "a@example.com"

    @contextmanager
    def fake_db_session():
        yield MagicMock()

    with patch("api.services.auth_lifecycle.get_user_by_email", return_value=user):
        with patch("api.services.auth_lifecycle.get_db_session", fake_db_session):
            with patch(
                "api.services.auth_lifecycle.send_password_reset_email",
                side_effect=RuntimeError("resend email send failed"),
            ):
                forgot_password_request("a@example.com")


def test_resend_verification_send_failure_does_not_propagate() -> None:
    user = MagicMock()
    user.email = "a@example.com"
    user.is_email_verified = False

    @contextmanager
    def fake_db_session():
        yield MagicMock()

    with patch("api.services.auth_lifecycle.get_user_by_email", return_value=user):
        with patch("api.services.auth_lifecycle.get_db_session", fake_db_session):
            with patch(
                "api.services.auth_lifecycle.send_verification_email",
                side_effect=RuntimeError("resend email send failed"),
            ):
                from api.services.auth_lifecycle import resend_verification_email

                resend_verification_email("a@example.com")
