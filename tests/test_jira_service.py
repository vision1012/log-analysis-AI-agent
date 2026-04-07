"""Tests for deterministic JIRA normalization and hint extraction."""

from __future__ import annotations

from api.services.jira_service import _extract_hints, _flatten_rich_text, _normalize_ticket_key


def test_normalize_ticket_key_uppercases_and_validates() -> None:
    assert _normalize_ticket_key("abc-123") == "ABC-123"


def test_flatten_rich_text_handles_adf() -> None:
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "PaymentService timeout"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "in /srv/api/app.py"},
                ],
            }
        ],
    }
    out = _flatten_rich_text(adf)
    assert "PaymentService timeout" in out
    assert "/srv/api/app.py" in out


def test_extract_hints_from_clean_text() -> None:
    text = (
        "prod outage in paymentservice. "
        "Exception thrown at /srv/payment/handler.py and C:\\apps\\svc\\main.py. "
        "HTTP 503 observed."
    )
    hints = _extract_hints(text, labels=["sev1", "payments"])
    assert "paymentservice" in hints.service_names
    assert "prod" in hints.environment_names
    assert "/srv/payment/handler.py" in hints.file_paths
    assert any(path.startswith("C:\\apps\\svc\\") for path in hints.file_paths)
    assert "exception" in hints.error_keywords
    assert "503" in hints.error_keywords
    assert hints.labels == ["sev1", "payments"]
