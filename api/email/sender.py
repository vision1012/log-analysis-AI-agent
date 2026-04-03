"""Send plain-text email via configured :class:`api.email.provider.EmailProvider`."""

from __future__ import annotations

from api.email.provider import build_provider
from api.email.settings import load_email_settings


def send_plain_text_email(to_addr: str, subject: str, body: str) -> None:
    """
    Deliver a plain-text message using ``EMAIL_PROVIDER`` (``log`` or ``smtp``).

    In ``log`` mode, the full body (including verification/reset URLs) is written to logs.
    SMTP credentials are never logged.
    """
    settings = load_email_settings()
    build_provider(settings).send_plain_text(to_addr, subject, body)
