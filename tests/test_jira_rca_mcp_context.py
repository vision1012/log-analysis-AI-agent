"""Jira/log RCA integration with MCP UnifiedInvestigationContext."""

from __future__ import annotations

from unittest.mock import patch

from api.services.jira_rca_orchestration_service import run_jira_rca
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.jira_models import McpTicketContext
from schemas.jira import JiraExtractedHints, JiraNormalizedTicket
from schemas.jira_rca import JiraRcaRunRequest


def test_jira_log_ranking_uses_mcp_context_boost() -> None:
    logs = """
2026-04-08T09:22:10Z ERROR auth-service timeout
Traceback (most recent call last):
  File "/srv/auth/otp_service.py", line 77, in validate_otp
TimeoutError: OTP verification timed out
"""
    mcp_ctx = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(
            issue_key="PROJ-221",
            summary="OTP timeout in otp_service.py",
            status="In Progress",
            labels=["auth"],
        ),
        commits=[
            McpCommit(
                sha="deadbeef1234",
                author="dev1",
                changed_files=["/srv/auth/otp_service.py"],
            )
        ],
        pull_requests=[
            McpPullRequest(
                number=7,
                title="Fix OTP",
                author="dev1",
                changed_files=["/srv/auth/otp_service.py"],
            )
        ],
    )
    body = JiraRcaRunRequest(
        log_content=logs,
        ticket=JiraNormalizedTicket(
            ticket_id="221",
            ticket_key="PROJ-221",
            summary="OTP timeout",
            description="",
            comments_text="",
            status="Open",
            priority="High",
            labels=["auth"],
            created_at="2026-04-08T09:00:00Z",
            updated_at="2026-04-08T09:30:00Z",
            url="https://example.atlassian.net/browse/PROJ-221",
            cleaned_text_body="otp timeout",
        ),
    )
    with patch(
        "api.services.jira_rca_orchestration_service._fetch_mcp_context_and_enrich_hints",
        return_value=(
            JiraExtractedHints(
                service_names=["auth-service"],
                file_paths=["/srv/auth/otp_service.py"],
                error_keywords=["timeout"],
            ),
            mcp_ctx,
        ),
    ):
        resp = run_jira_rca(body)

    top = (resp.rca.rca_result.get("candidate_root_causes") or [])[0]
    signal_scores = top.get("signal_scores") or {}
    assert any(k.startswith("mcp_") for k in signal_scores)
    assert top.get("mcp_artifact_refs")
    assert resp.explanation_payload.mcp_context_summary.get("jira_ticket_key") == "PROJ-221"
    assert "MCP context supports" in resp.explanation_payload.explanation
    assert resp.rca.evidence_summary.get("bundle_count", 0) >= 1
