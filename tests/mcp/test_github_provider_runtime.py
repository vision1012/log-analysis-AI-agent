"""Tests for GitHub MCP provider runtime connection support."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mcp.config import MCPFetchParams
from mcp.providers.github_provider import GitHubProvider
from mcp.runtime_connection import ProviderRuntimeConnection


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("GITHUB_MCP_ENABLED", "true")


def _mock_response(payload) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_github_provider_uses_runtime_repo_and_token(github_env) -> None:
    runtime = ProviderRuntimeConnection(
        connection_id="conn-gh-1",
        workspace_id="team-b",
        provider="github",
        org_name="acme",
        repo_name="payments",
        credentials={"token": "ghp_runtime_token"},
        source="database",
    )
    provider = GitHubProvider(runtime_connection=runtime)
    seen_urls: list[str] = []

    def _urlopen(req, timeout=15):
        seen_urls.append(req.full_url)
        if req.full_url.endswith("/user"):
            return _mock_response({"login": "bot"})
        if "/repos/acme/payments/commits" in req.full_url:
            return _mock_response([])
        if "/repos/acme/payments/pulls" in req.full_url:
            return _mock_response([])
        raise AssertionError(req.full_url)

    with patch("mcp.providers.github_provider.request.urlopen", side_effect=_urlopen):
        context = provider.fetch(MCPFetchParams(ticket_key="OPS-1", workspace_id="team-b"))

    assert any("/repos/acme/payments/commits" in url for url in seen_urls)
    assert context.source_metadata
    assert "connection=conn-gh-1" in context.source_metadata[0].detail


def test_github_provider_env_fallback_when_no_runtime(github_env, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
    monkeypatch.setenv("GITHUB_REPO", "env-org/env-repo")
    provider = GitHubProvider()
    seen_urls: list[str] = []

    def _urlopen(req, timeout=15):
        seen_urls.append(req.full_url)
        if req.full_url.endswith("/user"):
            return _mock_response({"login": "bot"})
        if "/repos/env-org/env-repo/commits" in req.full_url:
            return _mock_response([])
        if "/repos/env-org/env-repo/pulls" in req.full_url:
            return _mock_response([])
        raise AssertionError(req.full_url)

    with patch("mcp.providers.github_provider.request.urlopen", side_effect=_urlopen):
        provider.fetch(MCPFetchParams(ticket_key="OPS-1"))

    assert any("/repos/env-org/env-repo/commits" in url for url in seen_urls)


def test_resolve_github_fetch_window_expands_narrow_log_span(github_env, monkeypatch) -> None:
    monkeypatch.setenv("MCP_GITHUB_LOOKBACK_DAYS", "14")
    from mcp.providers.github_provider import _resolve_github_fetch_window

    since, until = _resolve_github_fetch_window(
        MCPFetchParams(
            ticket_key="OPS-1",
            start_time="2026-06-24T10:00:01Z",
            end_time="2026-06-24T10:00:03Z",
        )
    )
    assert since == "2026-06-10T10:00:03Z"
    assert until == "2026-06-24T10:00:03Z"


def test_resolve_github_fetch_window_unbounded_without_times(github_env) -> None:
    from mcp.providers.github_provider import _resolve_github_fetch_window

    since, until = _resolve_github_fetch_window(MCPFetchParams(ticket_key="OPS-1"))
    assert since is None
    assert until is None


def test_github_provider_passes_expanded_since_to_api(github_env, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
    monkeypatch.setenv("GITHUB_REPO", "env-org/env-repo")
    monkeypatch.setenv("MCP_GITHUB_LOOKBACK_DAYS", "7")
    provider = GitHubProvider()
    seen_urls: list[str] = []

    def _urlopen(req, timeout=15):
        seen_urls.append(req.full_url)
        if req.full_url.endswith("/user"):
            return _mock_response({"login": "bot"})
        if "/repos/env-org/env-repo/commits" in req.full_url:
            assert "since=2026-06-17T12%3A00%3A00Z" in req.full_url
            assert "until=2026-06-24T12%3A00%3A00Z" in req.full_url
            return _mock_response([])
        if "/repos/env-org/env-repo/pulls" in req.full_url:
            return _mock_response([])
        raise AssertionError(req.full_url)

    with patch("mcp.providers.github_provider.request.urlopen", side_effect=_urlopen):
        provider.fetch(
            MCPFetchParams(
                ticket_key="OPS-1",
                start_time="2026-06-24T11:00:00Z",
                end_time="2026-06-24T12:00:00Z",
            )
        )

    assert any("/repos/env-org/env-repo/commits" in url for url in seen_urls)


def test_pr_within_lookback_uses_merged_at_not_created_at(github_env) -> None:
    from mcp.providers.github_provider import _pr_within_lookback

    pr = {
        "created_at": "2026-06-01T10:00:00Z",
        "updated_at": "2026-06-20T10:00:00Z",
        "merged_at": "2026-06-22T10:00:00Z",
    }
    assert _pr_within_lookback(pr, since="2026-06-10T10:00:03Z", until="2026-06-24T10:00:03Z")
    assert not _pr_within_lookback(pr, since="2026-06-25T00:00:00Z", until="2026-06-24T10:00:03Z")


def test_pr_within_lookback_keeps_pr_created_after_log_window(github_env) -> None:
    from mcp.providers.github_provider import _pr_within_lookback

    pr = {
        "created_at": "2026-06-25T10:00:00Z",
        "updated_at": "2026-06-25T12:00:00Z",
        "merged_at": "2026-06-25T12:00:00Z",
    }
    assert _pr_within_lookback(pr, since="2026-06-10T10:00:03Z", until="2026-06-24T10:00:03Z")


def test_fetch_pull_requests_populates_changed_files(github_env, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
    monkeypatch.setenv("GITHUB_REPO", "env-org/env-repo")
    from mcp.providers.github_provider import _GitHubClientConfig, _fetch_pull_requests

    client = _GitHubClientConfig(token="ghp_env", api_base="https://api.github.com", owner="env-org", repo="env-repo")

    def _github_get(path, *, client, query=None):
        if path.endswith("/pulls"):
            return [
                {
                    "number": 9,
                    "title": "LAAA-83 integration settings",
                    "state": "closed",
                    "merged_at": "2026-06-25T12:00:00Z",
                    "created_at": "2026-06-25T10:00:00Z",
                    "updated_at": "2026-06-25T12:00:00Z",
                    "user": {"login": "dev"},
                    "html_url": "https://github.com/env-org/env-repo/pull/9",
                }
            ]
        if path.endswith("/pulls/9/files"):
            return [{"filename": "src/api/http/parseIntegrationsApi.ts"}]
        raise AssertionError(path)

    with patch("mcp.providers.github_provider._github_get", side_effect=_github_get):
        prs = _fetch_pull_requests(client, since="2026-06-10T10:00:03Z", until="2026-06-24T10:00:03Z")

    assert len(prs) == 1
    assert prs[0].changed_files == ["src/api/http/parseIntegrationsApi.ts"]
