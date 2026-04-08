"""Tests for deterministic JIRA normalization and hint extraction."""

from __future__ import annotations

from unittest.mock import patch
from urllib import error as urlerror

import pytest

from api.services.jira_service import (
    JiraConfigError,
    JiraExternalApiError,
    _extract_hints,
    _fetch_issue_from_jira,
    _flatten_rich_text,
    _jira_config_from_env,
    _normalize_ticket_key,
)


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


def test_jira_config_rejects_invalid_base_url() -> None:
    with (
        patch.dict(
            "os.environ",
            {"JIRA_BASE_URL": "not-a-url", "JIRA_EMAIL": "a@b.com", "JIRA_API_TOKEN": "token"},
            clear=False,
        ),
        pytest.raises(JiraConfigError),
    ):
        _jira_config_from_env()


def test_jira_config_rejects_invalid_email() -> None:
    with (
        patch.dict(
            "os.environ",
            {"JIRA_BASE_URL": "https://example.atlassian.net", "JIRA_EMAIL": "invalid", "JIRA_API_TOKEN": "token"},
            clear=False,
        ),
        pytest.raises(JiraConfigError),
    ):
        _jira_config_from_env()


def test_fetch_issue_retries_then_raises_sanitized_error() -> None:
    cfg = {"base_url": "https://example.atlassian.net", "email": "dev@example.com", "api_token": "token"}
    with (
        patch("api.services.jira_service.request.urlopen", side_effect=urlerror.URLError("down")),
        patch.dict("os.environ", {"JIRA_TIMEOUT_SEC": "5", "JIRA_MAX_RETRIES": "1"}, clear=False),
        pytest.raises(JiraExternalApiError) as exc,
    ):
        _fetch_issue_from_jira(cfg, "PROJ-1")
    assert "network failure" in str(exc.value)
