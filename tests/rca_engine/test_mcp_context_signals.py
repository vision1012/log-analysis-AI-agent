"""Tests for MCP context additive RCA signals."""

from __future__ import annotations

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.jira_models import McpTicketContext
from rca_engine.mcp_context_signals import (
    compute_mcp_context_signals_for_path,
    jira_log_mcp_boost,
    mcp_context_has_data,
)


def test_no_context_returns_zeros() -> None:
    signals, refs = compute_mcp_context_signals_for_path("/srv/auth/handler.py", None)
    assert all(v == 0.0 for v in signals.values())
    assert refs["matched_commits"] == []
    assert not mcp_context_has_data(None)


def test_changed_file_match_from_github_commit() -> None:
    ctx = UnifiedInvestigationContext(
        commits=[
            McpCommit(
                sha="abc123def456",
                author="dev1",
                message="fix handler timeout",
                changed_files=["src/auth/handler.py", "README.md"],
            )
        ],
        pull_requests=[],
    )
    path = "/app/src/auth/handler.py"
    signals, refs = compute_mcp_context_signals_for_path(path, ctx)
    assert signals["recent_commit_match"] == 1.0
    assert signals["changed_file_match"] == 1.0
    assert len(refs["matched_commits"]) == 1
    assert "handler.py" in refs["matched_changed_files"][0]


def test_jira_ticket_and_label_match() -> None:
    ctx = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(
            issue_key="PROJ-9",
            summary="auth-service timeout in handler.py",
            description="users cannot login",
            status="Open",
            labels=["auth-service", "timeout"],
        )
    )
    signals, refs = compute_mcp_context_signals_for_path("/srv/auth/handler.py", ctx)
    assert signals["jira_ticket_match"] == 1.0
    assert signals["jira_label_match"] == 1.0
    assert refs["jira_ticket_key"] == "PROJ-9"


def test_pr_match_boosts_jira_log_score() -> None:
    ctx = UnifiedInvestigationContext(
        pull_requests=[
            McpPullRequest(
                number=42,
                title="Fix OTP service",
                author="dev2",
                changed_files=["/srv/auth/otp_service.py"],
            )
        ]
    )
    signals, _ = compute_mcp_context_signals_for_path("/srv/auth/otp_service.py", ctx)
    assert signals["recent_pr_match"] == 1.0
    assert signals["changed_file_match"] == 1.0
    boost = jira_log_mcp_boost(signals)
    assert boost > 0.0
    assert boost <= 0.25


def test_pr_match_from_jira_key_in_title() -> None:
    ctx = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(
            issue_key="LAAA-83",
            summary="GitHub integration settings",
            description="",
            status="Open",
            labels=[],
        ),
        pull_requests=[
            McpPullRequest(
                number=12,
                title="LAAA-83: fix GitHub integration settings",
                author="dev4",
                changed_files=["README.md"],
            )
        ],
    )
    path = "/Users/jay027/Desktop/github_repo/LogIQ_debug_agent_UI/src/api/http/parseIntegrationsApi.ts"
    signals, refs = compute_mcp_context_signals_for_path(path, ctx)
    assert signals["recent_pr_match"] > 0
    assert len(refs["matched_pull_requests"]) == 1


def test_changed_file_match_from_pr_partial_basename() -> None:
    ctx = UnifiedInvestigationContext(
        pull_requests=[
            McpPullRequest(
                number=7,
                title="Update parser",
                author="dev3",
                changed_files=["src/api/http/parseIntegrationsApi.ts"],
            )
        ]
    )
    path = "/Users/jay027/Desktop/github_repo/LogIQ_debug_agent_UI/src/api/http/parseIntegrationsApi.ts"
    signals, refs = compute_mcp_context_signals_for_path(path, ctx)
    assert signals["changed_file_match"] == 1.0
    assert signals["recent_commit_match"] == 1.0
    assert "parseIntegrationsApi.ts" in refs["matched_changed_files"][0]


def test_normalize_candidate_path_strips_absolute_prefix() -> None:
    from rca_engine.mcp_context_signals import normalize_candidate_path

    path = "/Users/jay027/Desktop/github_repo/LogIQ_debug_agent_UI/src/api/http/parseIntegrationsApi.ts"
    assert normalize_candidate_path(path) == "src/api/http/parseIntegrationsApi.ts"
