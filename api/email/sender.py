"""Send plain-text email via configured :class:`api.email.provider.EmailProvider`."""

from __future__ import annotations

import logging

from api.email.provider import build_provider
from api.email.settings import load_email_settings

logger = logging.getLogger("api.email.sender")


def send_plain_text_email(to_addr: str, subject: str, body: str) -> None:
    """
    Deliver a plain-text message using ``EMAIL_PROVIDER`` (``log``, ``resend``, or ``smtp``).

    In ``log`` mode, the full body (including verification/reset URLs) is written to logs.
    API keys and SMTP credentials are never logged.

    On success, emits one concise INFO line (provider, recipient, subject) for observability.
    """
    settings = load_email_settings()
    build_provider(settings).send_plain_text(to_addr, subject, body)
    logger.info(
        "email delivered provider=%s to=%s subject=%s",
        settings.email_provider,
        to_addr,
        subject,
    )
