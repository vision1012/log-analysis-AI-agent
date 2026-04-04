"""Email provider selection and Resend error handling (no real network)."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

from api.email.provider import ResendEmailProvider, SmtpEmailProvider, build_provider
from api.email.settings import EmailSettings, load_email_settings


def test_build_provider_log_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    s = load_email_settings()
    assert s.email_provider == "log"
    p = build_provider(s)
    assert type(p).__name__ == "LogEmailProvider"


def test_build_provider_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USERNAME", "user@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password-placeholder")
    s = load_email_settings()
    assert s.email_provider == "smtp"
    p = build_provider(s)
    assert type(p).__name__ == "SmtpEmailProvider"


def test_smtp_requires_username_and_password() -> None:
    settings = EmailSettings(
        email_provider="smtp",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        smtp_from_email="",
        smtp_use_tls=True,
        app_base_url="http://localhost:5173",
        email_verification_path="/verify-email",
        password_reset_path="/reset-password",
        email_verification_ttl_hours=24,
        password_reset_ttl_hours=1,
        resend_api_key="",
        email_from="",
    )
    provider = SmtpEmailProvider(settings)
    with pytest.raises(RuntimeError, match="SMTP_USERNAME"):
        provider.send_plain_text("a@example.com", "Subject", "body")


def test_build_provider_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "onboarding@resend.dev")
    s = load_email_settings()
    assert s.email_provider == "resend"
    p = build_provider(s)
    assert type(p).__name__ == "ResendEmailProvider"


def test_resend_send_plain_text_logs_safe_error_on_http_422() -> None:
    settings = EmailSettings(
        email_provider="resend",
        smtp_host="",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        smtp_from_email="",
        smtp_use_tls=True,
        app_base_url="http://localhost:5173",
        email_verification_path="/verify-email",
        password_reset_path="/reset-password",
        email_verification_ttl_hours=24,
        password_reset_ttl_hours=1,
        resend_api_key="re_secret_not_logged",
        email_from="test@example.com",
    )
    provider = ResendEmailProvider(settings)

    err_json = json.dumps({"message": "Invalid `from` field"}).encode("utf-8")
    http_err = urllib.error.HTTPError(
        "https://api.resend.com/emails",
        422,
        "Unprocessable Entity",
        hdrs={},
        fp=BytesIO(err_json),
    )

    with patch("api.email.provider.urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(RuntimeError, match="resend email send failed"):
            provider.send_plain_text("u@example.com", "Subject", "body")
