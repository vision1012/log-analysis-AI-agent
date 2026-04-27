"""Endpoint tests for JIRA-first RCA run route."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.services.jira_rca_orchestration_service import NoUsefulSignalsError


def test_jira_rca_run_success() -> None:
    with patch("api.routes.jira_rca.run_jira_rca") as mock_run:
        mock_run.return_value = {
            "ticket_summary": {
                "ticket_key": "PROJ-1",
                "ticket_id": "1001",
                "summary": "sample",
                "status": "Open",
                "priority": "High",
                "url": "https://example.atlassian.net/browse/PROJ-1",
            },
            "extracted_ticket_hints": {
                "service_names": [],
                "environment_names": [],
                "file_paths": [],
                "error_keywords": [],
                "labels": [],
            },
            "derived_log_signals": {
                "severity_counts": {"error": 1},
                "repeated_error_lines": [],
                "error_keywords": ["error"],
                "service_names": [],
                "file_paths": [],
                "stack_traces": [],
                "time_window": None,
            },
            "derived_signal_bundle": {
                "ticket_hints": {
                    "service_names": [],
                    "environment_names": [],
                    "file_paths": [],
                    "error_keywords": [],
                    "labels": [],
                },
                "log_signals": {
                    "severity_counts": {"error": 1},
                    "repeated_error_lines": [],
                    "error_keywords": ["error"],
                    "service_names": [],
                    "file_paths": [],
                    "stack_traces": [],
                    "time_window": None,
                },
                "merged": {
                    "service_names": [],
                    "environment_names": [],
                    "file_paths": [],
                    "error_keywords": ["error"],
                    "labels": [],
                },
            },
            "rca": {
                "anomaly_id": "an-1",
                "run_status": "completed",
                "run_id": "run-1",
                "rca_result": {"candidate_root_causes": [{"file_id": "f1"}]},
                "evidence_summary": {"bundle_count": 1, "evidence_refs": ["b1"]},
            },
            "explanation_payload": {
                "root_cause": {"source": "top_ranked_candidate", "file_id": "f1", "confidence": 0.7},
                "assist_status": "ok",
                "ticket_context_summary": {"ticket_key": "PROJ-1", "summary": "sample"},
                "log_signal_summary": {"severity_counts": {"error": 1}},
                "explanation": "Deterministic RCA ranked f1 from evidence.",
                "remediation_suggestions": ["validate candidate", "apply reversible mitigation"],
                "confidence_note": "Deterministic RCA is authoritative.",
            },
            "relationship_bundle": {
                "ticket_key": "PROJ-1",
                "anomaly_id": "an-1",
                "rca_target_file": "services/payments.py",
                "candidate_services": ["paymentservice"],
                "candidate_errors": ["timeout", "error"],
                "candidate_file_paths": ["services/payments.py"],
                "entity_refs": {
                    "ticket": ["PROJ-1"],
                    "anomaly": ["an-1"],
                    "service": ["paymentservice"],
                    "error": ["timeout", "error"],
                    "file": ["services/payments.py"],
                },
            },
        }
        client = TestClient(app)
        r = client.post(
            "/api/v1/jira/rca/run",
            json={
                "anomaly_id": "an-1",
                "ticket_key": "PROJ-1",
                "log_content": "2026-04-07T10:00:00Z ERROR boom",
            },
        )
    assert r.status_code == 200
    assert r.json()["rca"]["run_status"] == "completed"
    assert r.json()["explanation_payload"]["root_cause"]["source"] == "top_ranked_candidate"
    assert r.json()["relationship_bundle"]["ticket_key"] == "PROJ-1"


def test_jira_rca_run_maps_no_signal_error() -> None:
    with patch("api.routes.jira_rca.run_jira_rca", side_effect=NoUsefulSignalsError("none found")):
        client = TestClient(app)
        r = client.post(
            "/api/v1/jira/rca/run",
            json={
                "anomaly_id": "an-1",
                "ticket_key": "PROJ-1",
                "log_content": "2026-04-07T10:00:00Z INFO hello",
            },
        )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "no_useful_signals"


def test_jira_rca_route_accepts_multipart_log_upload() -> None:
    mfa_logs = (
        "2026-04-08T09:22:10Z ERROR auth-service MFA timeout /srv/auth/mfa_handler.py\n"
        "Traceback (most recent call last):\n"
        "  File \"/srv/auth/mfa_handler.py\", line 118, in verify_mfa\n"
        "  File \"/srv/auth/otp_service.py\", line 77, in validate_otp\n"
        "TimeoutError: OTP verification timed out\n"
    )
    ticket_json = (
        '{"ticket_id":"221","ticket_key":"PROJ-221","summary":"MFA timeout in auth-service",'
        '"description":"traceback present","comments_text":"users blocked","status":"Open",'
        '"priority":"High","labels":["auth"],"created_at":"2026-04-08T09:00:00Z",'
        '"updated_at":"2026-04-08T09:30:00Z","url":"https://example.atlassian.net/browse/PROJ-221",'
        '"cleaned_text_body":"mfa timeout auth-service"}'
    )
    client = TestClient(app)
    r = client.post(
        "/api/v1/jira/rca/run",
        data={"ticket_key": "PROJ-221", "ticket": ticket_json},
        files={"log_file": ("mfa.log", mfa_logs, "text/plain")},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["derived_log_signals"]["file_paths"]
    assert payload["derived_log_signals"]["stack_traces"]
    assert payload["rca"]["rca_result"]["candidate_root_causes"]


def test_jira_rca_route_preserves_json_log_content() -> None:
    log_text = "2026-04-08T09:22:10Z ERROR auth-service timeout /srv/auth/mfa_handler.py"
    with patch("api.routes.jira_rca.run_jira_rca") as mock_run:
        mock_run.return_value = {
            "ticket_summary": {
                "ticket_key": "PROJ-1",
                "ticket_id": "1001",
                "summary": "sample",
                "status": "Open",
                "priority": "High",
                "url": "https://example.atlassian.net/browse/PROJ-1",
            },
            "extracted_ticket_hints": {"service_names": [], "environment_names": [], "file_paths": [], "error_keywords": [], "labels": []},
            "derived_log_signals": {
                "severity_counts": {"error": 1},
                "repeated_error_lines": [],
                "error_keywords": ["timeout"],
                "service_names": ["auth-service"],
                "file_paths": ["/srv/auth/mfa_handler.py"],
                "stack_traces": [],
                "time_window": None,
            },
            "derived_signal_bundle": {
                "ticket_hints": {"service_names": [], "environment_names": [], "file_paths": [], "error_keywords": [], "labels": []},
                "log_signals": {
                    "severity_counts": {"error": 1},
                    "repeated_error_lines": [],
                    "error_keywords": ["timeout"],
                    "service_names": ["auth-service"],
                    "file_paths": ["/srv/auth/mfa_handler.py"],
                    "stack_traces": [],
                    "time_window": None,
                },
                "merged": {
                    "service_names": ["auth-service"],
                    "environment_names": [],
                    "file_paths": ["/srv/auth/mfa_handler.py"],
                    "error_keywords": ["timeout"],
                    "labels": [],
                },
            },
            "rca": {
                "anomaly_id": None,
                "run_status": "completed",
                "run_id": "run-1",
                "rca_result": {"candidate_root_causes": [{"file_id": "f1"}]},
                "evidence_summary": {"bundle_count": 0, "evidence_refs": []},
            },
            "explanation_payload": {
                "root_cause": {"source": "top_ranked_candidate", "file_id": "f1", "confidence": 0.7},
                "assist_status": "ok",
                "ticket_context_summary": {"ticket_key": "PROJ-1", "summary": "sample"},
                "log_signal_summary": {"severity_counts": {"error": 1}},
                "explanation": "Deterministic RCA ranked f1 from evidence.",
                "remediation_suggestions": ["validate candidate"],
                "confidence_note": "Deterministic RCA is authoritative.",
            },
            "relationship_bundle": {
                "ticket_key": "PROJ-1",
                "anomaly_id": None,
                "rca_target_file": "/srv/auth/mfa_handler.py",
                "candidate_services": ["auth-service"],
                "candidate_errors": ["timeout"],
                "candidate_file_paths": ["/srv/auth/mfa_handler.py"],
                "entity_refs": {"ticket": ["PROJ-1"], "anomaly": [], "service": ["auth-service"], "error": ["timeout"], "file": ["/srv/auth/mfa_handler.py"]},
            },
        }
        client = TestClient(app)
        r = client.post(
            "/api/v1/jira/rca/run",
            json={"ticket_key": "PROJ-1", "log_content": log_text},
        )
    assert r.status_code == 200
    called_request = mock_run.call_args.args[0]
    assert called_request.log_content == log_text
