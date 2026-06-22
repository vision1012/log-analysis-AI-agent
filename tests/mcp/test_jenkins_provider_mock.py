"""Tests for Jenkins MCP provider with mocked API responses."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from mcp.config import MCPFetchParams
from mcp.providers.jenkins_provider import JenkinsProvider


@pytest.fixture
def jenkins_env(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("JENKINS_MCP_ENABLED", "true")
    monkeypatch.setenv("JENKINS_BASE_URL", "https://jenkins.example.com")
    monkeypatch.setenv("JENKINS_USER", "ci-user")
    monkeypatch.setenv("JENKINS_API_TOKEN", "token123")
    monkeypatch.setenv("JENKINS_JOB_NAME", "platform/deploy-service")


def _mock_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@patch("mcp.providers.jenkins_provider.request.urlopen")
def test_jenkins_provider_fetch_normalizes_builds(mock_urlopen, jenkins_env):
    job_payload = {
        "builds": [
            {
                "number": 42,
                "url": "https://jenkins.example.com/job/platform/job/deploy-service/42/",
                "result": "SUCCESS",
                "timestamp": 1_700_000_000_000,
                "duration": 120_000,
                "actions": [
                    {
                        "causes": [{"userName": "deploy-bot"}],
                        "lastBuiltRevision": {
                            "SHA1": "abc123def456",
                            "branch": [{"name": "main"}],
                        },
                    },
                    {
                        "parameters": [
                            {"name": "ENVIRONMENT", "value": "production"},
                        ],
                    },
                ],
                "changeSet": {"items": [{"commitId": "abc123def456"}]},
            }
        ]
    }
    mock_urlopen.return_value = _mock_response(job_payload)

    provider = JenkinsProvider()
    assert provider.is_enabled() is True
    assert provider.is_configured() is True

    ctx = provider.fetch(MCPFetchParams(ticket_key="OPS-1"))
    assert len(ctx.build_events) == 1
    build = ctx.build_events[0]
    assert build.build_number == 42
    assert build.status == "SUCCESS"
    assert build.branch == "main"
    assert build.commit_sha == "abc123def456"
    assert build.triggered_by == "deploy-bot"
    assert build.build_url.endswith("/42/")

    assert len(ctx.deployment_events) == 1
    dep = ctx.deployment_events[0]
    assert dep.environment == "production"
    assert dep.build_number == 42
    assert dep.commit_sha == "abc123def456"
    assert dep.deployment_url.endswith("/42/")

    assert len(ctx.source_metadata) == 1
    assert ctx.source_metadata[0].source == "jenkins"


@patch("mcp.providers.jenkins_provider.request.urlopen")
def test_jenkins_provider_health_check_ok(mock_urlopen, jenkins_env):
    mock_urlopen.return_value = _mock_response({"name": "deploy-service"})
    health = JenkinsProvider().health_check()
    assert health.source == "jenkins"
    assert health.enabled is True
    assert health.configured is True
    assert health.reachable is True


def test_jenkins_provider_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("JENKINS_MCP_ENABLED", "false")
    provider = JenkinsProvider()
    assert provider.is_enabled() is False
    health = provider.health_check()
    assert health.enabled is False


def test_jenkins_provider_not_configured_without_env(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("JENKINS_MCP_ENABLED", "true")
    for key in ("JENKINS_BASE_URL", "JENKINS_USER", "JENKINS_API_TOKEN", "JENKINS_JOB_NAME"):
        monkeypatch.delenv(key, raising=False)
    provider = JenkinsProvider()
    assert provider.is_configured() is False
    assert provider.fetch(MCPFetchParams(ticket_key="OPS-1")).build_events == []
