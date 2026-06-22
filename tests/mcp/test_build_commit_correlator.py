"""Tests for build/commit/deployment correlator."""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.context.build_commit_correlator import correlate_and_attach_metadata, correlate_investigation
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.common import SourceMetadata
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent


def _sample_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext(
        commits=[
            McpCommit(
                sha="abc123def4567890",
                message="Merge pull request #7 from feature/fix",
                author="dev",
                committed_at="2024-01-01T00:00:00Z",
            )
        ],
        pull_requests=[
            McpPullRequest(
                number=7,
                title="fix outage",
                state="closed",
                merged=True,
                author="dev",
                merged_at="2024-01-01T00:00:00Z",
            )
        ],
        build_events=[
            BuildEvent(
                build_id="jenkins:99",
                build_number=99,
                build_url="https://jenkins/job/app/99/",
                status="SUCCESS",
                branch="main",
                commit_sha="abc123def4567890",
                started_at="2024-01-01T00:05:00Z",
                completed_at="2024-01-01T00:10:00Z",
            )
        ],
        deployment_events=[
            DeploymentEvent(
                deployment_id="jenkins-deploy:99:production",
                environment="production",
                status="SUCCESS",
                commit_sha="abc123def4567890",
                build_number=99,
                deployed_at="2024-01-01T00:10:00Z",
                deployment_url="https://jenkins/job/app/99/",
            )
        ],
        source_metadata=[
            SourceMetadata(
                source="github",
                fetched_at=datetime.now(timezone.utc),
                ok=True,
                detail="test",
            )
        ],
    )


def test_correlate_investigation_links_commit_build_deployment():
    links = correlate_investigation(_sample_context())
    relations = {link.relation for link in links}
    assert "pr_to_commit" in relations
    assert "commit_to_build" in relations
    assert "build_to_deployment" in relations

    commit_build = next(l for l in links if l.relation == "commit_to_build")
    assert commit_build.build_number == 99
    assert commit_build.commit_sha.startswith("abc123")

    build_deploy = next(l for l in links if l.relation == "build_to_deployment")
    assert build_deploy.build_number == 99
    assert build_deploy.environment == "production"


def test_correlate_and_attach_metadata_appends_source_metadata():
    ctx = correlate_and_attach_metadata(_sample_context())
    correlator_meta = [m for m in ctx.source_metadata if m.source == "correlator"]
    assert len(correlator_meta) == 1
    assert len(correlator_meta[0].correlations) >= 3
    assert correlator_meta[0].correlations[0].relation in {
        "pr_to_commit",
        "commit_to_build",
        "build_to_deployment",
    }


def test_correlate_empty_context_no_links():
    assert correlate_investigation(UnifiedInvestigationContext()) == []
