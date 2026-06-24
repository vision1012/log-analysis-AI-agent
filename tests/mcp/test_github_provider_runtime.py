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
