"""Tests for deterministic JIRA-first RCA orchestration service."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from api.services.jira_rca_orchestration_service import (
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


def test_jira_rca_run_request_requires_ticket_or_key() -> None:
    with pytest.raises(ValidationError):
        JiraRcaRunRequest(anomaly_id="an-1", log_content="ERROR sample log")


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
        patch(
            "api.services.jira_rca_orchestration_service.get_rca_explanation",
            return_value={
                "explanation_summary": "Evidence points to deterministic candidate.",
                "confidence_alignment_note": "Deterministic ranking is source of truth.",
                "optional_patch_direction": "consider defensive check in candidate path",
            },
        ),
    ):
        resp = run_jira_rca(body)
    assert resp.rca.run_status == "completed"
    assert resp.rca.evidence_summary.get("bundle_count") == 1
    assert resp.rca.evidence_summary.get("investigation_id")
    assert resp.explanation_payload.root_cause.get("source") == "top_ranked_candidate"
    assert resp.explanation_payload.assist_status == "ok"
    assert resp.explanation_payload.explanation
    assert resp.explanation_payload.remediation_suggestions
    assert resp.relationship_bundle.ticket_key == "PROJ-123"
    assert resp.relationship_bundle.anomaly_id == "an-1"
    assert "paymentservice" in resp.relationship_bundle.candidate_services


def test_run_jira_rca_without_anomaly_uses_jira_log_mode() -> None:
    body = JiraRcaRunRequest(
        log_content=(
            "2026-04-07T10:01:01Z ERROR timeout at /srv/payments/handler.py\n"
            "2026-04-07T10:01:02Z ERROR timeout at /srv/payments/handler.py\n"
        ),
        ticket=JiraNormalizedTicket(
            ticket_id="100",
            ticket_key="PROJ-124",
            summary="payments failing in prod",
            description="timeouts observed",
            comments_text="see logs",
            status="Open",
            priority="High",
            labels=["sev1"],
            created_at="2026-04-07T10:00:00Z",
            updated_at="2026-04-07T10:10:00Z",
            url="https://example.atlassian.net/browse/PROJ-124",
            cleaned_text_body="payments failing in prod timeout",
        ),
        ticket_hints=JiraExtractedHints(
            service_names=["paymentservice"],
            environment_names=["prod"],
            file_paths=["/srv/payments/handler.py"],
            error_keywords=["timeout"],
            labels=["sev1"],
        ),
    )
    with (
        patch("api.services.jira_rca_orchestration_service.trigger_manual_rca") as mock_trigger,
        patch("api.services.jira_rca_orchestration_service.get_rca_result_view") as mock_view,
    ):
        resp = run_jira_rca(body)
    mock_trigger.assert_not_called()
    mock_view.assert_not_called()
    assert resp.rca.run_status == "completed"
    assert resp.rca.anomaly_id is None
    assert resp.relationship_bundle.anomaly_id is None
    assert resp.rca.rca_result.get("mode") == "jira_log"
    candidates = resp.rca.rca_result.get("candidate_root_causes") or []
    assert candidates
    assert any(c.get("path") == "/srv/payments/handler.py" for c in candidates)
    assert resp.derived_log_signals.file_paths
    assert resp.explanation_payload.explanation
    assert resp.rca.evidence_summary.get("evidence_highlights")


def test_jira_log_mode_mfa_timeout_traceback_produces_deterministic_evidence() -> None:
    mfa_logs = """
2026-04-08T09:22:10Z ERROR auth-service MFA timeout for user=42 in /srv/auth/mfa_handler.py
2026-04-08T09:22:11Z ERROR auth-service MFA timeout for user=42 in /srv/auth/mfa_handler.py
Traceback (most recent call last):
  File "/srv/auth/mfa_handler.py", line 118, in verify_mfa
  File "/srv/auth/otp_service.py", line 77, in validate_otp
TimeoutError: OTP verification timed out
"""
    body = JiraRcaRunRequest(
        ticket_key="PROJ-221",
        log_content=mfa_logs,
        ticket=JiraNormalizedTicket(
            ticket_id="221",
            ticket_key="PROJ-221",
            summary="MFA timeout in auth-service",
            description="timeouts with traceback in auth-service",
            comments_text="users cannot login",
            status="Open",
            priority="High",
            labels=["auth", "sev2"],
            created_at="2026-04-08T09:00:00Z",
            updated_at="2026-04-08T09:30:00Z",
            url="https://example.atlassian.net/browse/PROJ-221",
            cleaned_text_body="MFA timeout auth-service traceback",
        ),
    )
    resp = run_jira_rca(body)
    candidates = resp.rca.rca_result.get("candidate_root_causes") or []
    assert candidates
    assert any("/srv/auth/mfa_handler.py" == c.get("path") for c in candidates)
    assert any("/srv/auth/otp_service.py" == c.get("path") for c in candidates)
    assert resp.derived_log_signals.service_names
    assert "timeout" in resp.derived_log_signals.error_keywords
    assert resp.derived_log_signals.stack_traces
    assert resp.explanation_payload.explanation
    assert resp.rca.evidence_summary.get("evidence_highlights")
    top = (resp.rca.rca_result.get("candidate_root_causes") or [])[0]
    assert top.get("path") == "/srv/auth/otp_service.py"
    assert resp.explanation_payload.remediation_suggestions
    assert "deterministic" in resp.explanation_payload.explanation.lower()


def test_otp_timeout_single_error_and_single_quoted_traceback_still_extracts() -> None:
    """Single ERROR line + single-quoted File lines must still yield paths, signals, and candidates."""
    mfa_logs = """
2026-04-08T09:22:10Z [ERROR] auth-service OTP timeout in /srv/auth/mfa_handler.py
Traceback (most recent call last):
  File '/srv/auth/mfa_handler.py', line 118, in verify_mfa
  File '/srv/auth/otp_service.py', line 77, in validate_otp
TimeoutError: OTP verification timed out
"""
    body = JiraRcaRunRequest(
        ticket_key="PROJ-222",
        log_content=mfa_logs,
        ticket=JiraNormalizedTicket(
            ticket_id="222",
            ticket_key="PROJ-222",
            summary="OTP timeout",
            description="see logs",
            comments_text="",
            status="Open",
            priority="High",
            labels=[],
            created_at="2026-04-08T09:00:00Z",
            updated_at="2026-04-08T09:30:00Z",
            url="https://example.atlassian.net/browse/PROJ-222",
            cleaned_text_body="otp timeout",
        ),
    )
    sig = _derive_log_signals(mfa_logs)
    assert sig.severity_counts.get("error", 0) >= 1
    assert "/srv/auth/otp_service.py" in sig.file_paths
    assert sig.stack_traces

    resp = run_jira_rca(body)
    assert resp.derived_log_signals.error_keywords
    assert resp.rca.rca_result.get("candidate_root_causes")
    assert resp.rca.evidence_summary.get("evidence_highlights")
    assert resp.explanation_payload.explanation
