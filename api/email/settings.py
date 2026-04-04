"""Email delivery settings from environment (no secrets in code)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("api.email.settings")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_email_provider() -> str:
    """Return ``log``, ``smtp``, or ``resend``. Default ``log`` for local development."""
    raw = os.environ.get("EMAIL_PROVIDER", "log").strip().lower()
    if raw in ("smtp", "mail", "send"):
        return "smtp"
    if raw in ("resend",):
        return "resend"
    if raw in ("log", "logging", "dev", "console", ""):
        return "log"
    logger.warning("unknown EMAIL_PROVIDER=%r; defaulting to log", os.environ.get("EMAIL_PROVIDER"))
    return "log"


def _normalize_path(path: str, default: str) -> str:
    """Ensure path starts with ``/``."""
    p = (path or "").strip() or default
    return p if p.startswith("/") else f"/{p}"


@dataclass(frozen=True)
class EmailSettings:
    """SMTP / Resend + URLs for verification/reset links.

    ``app_base_url`` should be the **frontend** origin (e.g. Vite ``http://localhost:5173``) so links open
    in the browser app; verification/reset paths are appended below.

    When ``email_provider`` is ``resend``, set ``resend_api_key`` and ``email_from`` (verified domain in Resend).

    When ``email_provider`` is ``smtp``, set ``smtp_host``, ``smtp_username``, ``smtp_password``
    (Gmail: App Password), and usually ``smtp_from_email`` matching the sender address.
    """

    email_provider: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from_email: str
    smtp_use_tls: bool
    app_base_url: str
    email_verification_path: str
    password_reset_path: str
    email_verification_ttl_hours: int
    password_reset_ttl_hours: int
    resend_api_key: str
    email_from: str


def load_email_settings() -> EmailSettings:
    return EmailSettings(
        email_provider=_parse_email_provider(),
        smtp_host=os.environ.get("SMTP_HOST", "").strip(),
        smtp_port=_env_int("SMTP_PORT", 587),
        smtp_username=os.environ.get("SMTP_USERNAME", "").strip(),
        smtp_password=os.environ.get("SMTP_PASSWORD", "").strip(),
        smtp_from_email=os.environ.get("SMTP_FROM_EMAIL", "").strip(),
        smtp_use_tls=os.environ.get("SMTP_USE_TLS", "true").strip().lower() in ("1", "true", "yes"),
        # Frontend base for links in emails (not the API host unless your SPA is served there).
        app_base_url=os.environ.get("APP_BASE_URL", "http://localhost:5173").rstrip("/"),
        email_verification_path=_normalize_path(
            os.environ.get("EMAIL_VERIFICATION_PATH", "/verify-email"),
            "/verify-email",
        ),
        password_reset_path=_normalize_path(
            os.environ.get("PASSWORD_RESET_PATH", "/reset-password"),
            "/reset-password",
        ),
        email_verification_ttl_hours=_env_int("EMAIL_VERIFICATION_TTL_HOURS", 24),
        password_reset_ttl_hours=_env_int("PASSWORD_RESET_TTL_HOURS", 1),
        resend_api_key=os.environ.get("RESEND_API_KEY", "").strip(),
        email_from=os.environ.get("EMAIL_FROM", "").strip(),
    )


def email_delivery_mode() -> str:
    """Return ``log``, ``smtp``, or ``resend`` (alias for :attr:`EmailSettings.email_provider`)."""
    return load_email_settings().email_provider
