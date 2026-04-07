"""Tests for deterministic JIRA-first RCA orchestration service."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.services.jira_rca_orchestration_service import (
    MissingTicketContextError,
    _derive_log_signals,
    run_jira_rca,
)
from schemas.jira import JiraExtractedHints, JiraNormalizedTicket
from schemas.jira_rca import JiraRcaRunRequest


def test_derive_log_signals_extracts_expected_fields() -> None:
    logs = """
2026-04-07T10:01:01Z ERROR paymentservice timeout at /srv/payments/handler.py
2026-04-07T10:01:02Z ERROR paymentservice timeout at /srv/payments/handler.py
Traceback (most recent call last):
  File "/srv/payments/handler.py", line 42, in run
Exception: timeout
"""
    signals = _derive_log_signals(logs)
    assert signals.severity_counts.get("error", 0) >= 1
    assert signals.repeated_error_lines
    assert "timeout" in signals.error_keywords
    assert "paymentservice" in signals.service_names
    assert "/srv/payments/handler.py" in signals.file_paths
    assert signals.stack_traces
    assert signals.time_window is not None


def test_run_jira_rca_requires_ticket_context() -> None:
    body = JiraRcaRunRequest(anomaly_id="an-1", log_content="ERROR sample log")
    with pytest.raises(MissingTicketContextError):
        run_jira_rca(body)


def test_run_jira_rca_uses_existing_rca_engine_adapter() -> None:
    body = JiraRcaRunRequest(
        anomaly_id="an-1",
        log_content="2026-04-07T10:01:01Z ERROR paymentservice timeout",
        ticket=JiraNormalizedTicket(
            ticket_id="100",
            ticket_key="PROJ-123",
            summary="paymentservice failing in prod",
            description="timeout at /srv/payments/handler.py",
            comments_text="Exception repeats",
            status="Open",
            priority="High",
            labels=["sev1"],
            created_at="2026-04-07T10:00:00Z",
            updated_at="2026-04-07T10:10:00Z",
            url="https://example.atlassian.net/browse/PROJ-123",
            cleaned_text_body="paymentservice failing in prod timeout",
        ),
        ticket_hints=JiraExtractedHints(
            service_names=["paymentservice"],
            environment_names=["prod"],
            file_paths=["/srv/payments/handler.py"],
            error_keywords=["timeout", "exception"],
            labels=["sev1"],
        ),
    )
    with (
        patch(
            "api.services.jira_rca_orchestration_service.trigger_manual_rca",
            return_value={"status": "completed", "run_id": "rk-1"},
        ),
        patch(
            "api.services.jira_rca_orchestration_service.get_rca_result_view",
            return_value={
                "anomaly_id": "an-1",
                "accepted_root_cause": None,
                "candidate_root_causes": [{"file_id": "f1", "confidence": 0.7}],
                "latest_run_id": "rk-1",
                "evidence_refs": ["bundle-1"],
            },
        ),
    ):
        resp = run_jira_rca(body)
    assert resp.rca.run_status == "completed"
    assert resp.rca.evidence_summary.get("bundle_count") == 1
    assert resp.rca.evidence_summary.get("investigation_id")
