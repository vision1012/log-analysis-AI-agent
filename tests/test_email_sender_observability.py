"""Sender-level delivery logging (no secrets in log lines)."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest


def test_send_plain_text_email_logs_success_line(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    with patch.dict("os.environ", {"EMAIL_PROVIDER": "log"}, clear=False):
        from api.email.sender import send_plain_text_email

        send_plain_text_email("user@example.com", "Test subject", "body line")

    assert any(
        "email delivered" in r.message and "provider=log" in r.message and "user@example.com" in r.message
        for r in caplog.records
        if r.name == "api.email.sender"
    )


def test_resend_success_logs_message_id_and_sender_line(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "onboarding@resend.dev")

    import io
    import json
    import urllib.request

    payload = json.dumps({"id": "msg_abc123"}).encode("utf-8")

    class _Resp:
        def read(self) -> bytes:
            return payload

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with patch.object(urllib.request, "urlopen", return_value=_Resp()):
        from api.email.sender import send_plain_text_email

        send_plain_text_email("u@example.com", "Subj", "hello")

    assert any("resend api accepted id=msg_abc123" in r.message for r in caplog.records)
    assert any(
        r.name == "api.email.sender" and "email delivered" in r.message and "provider=resend" in r.message
        for r in caplog.records
    )
