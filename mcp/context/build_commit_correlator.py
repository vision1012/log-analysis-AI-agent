"""Correlate commits, builds, and deployments for investigation metadata."""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.common import InvestigationCorrelation, SourceMetadata
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.gitlab_models import McpDeploymentEvent, McpGitLabCommit
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent


def correlate_and_attach_metadata(context: UnifiedInvestigationContext) -> UnifiedInvestigationContext:
    """
    Build Commit→Build and Build→Deployment links from normalized MCP slices.

    Correlation metadata is appended to ``source_metadata``; RCA ranking is unchanged.
    """
    correlations = correlate_investigation(context)
    if not correlations:
        return context

    meta = SourceMetadata(
        source="correlator",
        fetched_at=datetime.now(timezone.utc),
        ok=True,
        detail=f"links={len(correlations)}",
        correlations=correlations,
    )
    data = context.model_dump()
    data["source_metadata"] = list(data.get("source_metadata") or []) + [meta.model_dump()]
    return UnifiedInvestigationContext.model_validate(data)


def correlate_investigation(context: UnifiedInvestigationContext) -> list[InvestigationCorrelation]:
    """Return investigation correlation links without mutating context."""
    links: list[InvestigationCorrelation] = []
    commit_shas = _collect_commit_shas(context)
    pr_by_sha = _pr_by_merge_sha(context)

    for sha in commit_shas:
        pr = pr_by_sha.get(sha)
        if pr is not None:
            links.append(
                InvestigationCorrelation(
                    relation="pr_to_commit",
                    from_ref=f"pr:{pr.number}",
                    to_ref=f"commit:{sha[:12]}",
                    commit_sha=sha,
                    pr_number=pr.number,
                )
            )

    for build in context.build_events:
        sha = (build.commit_sha or "").strip()
        if not sha:
            continue
        links.append(
            InvestigationCorrelation(
                relation="commit_to_build",
                from_ref=f"commit:{sha[:12]}",
                to_ref=f"build:{build.build_number}",
                commit_sha=sha,
                build_number=build.build_number,
            )
        )

    for dep in context.deployment_events:
        env, commit_sha, build_number, dep_id = _deployment_fields(dep)
        if build_number is not None:
            links.append(
                InvestigationCorrelation(
                    relation="build_to_deployment",
                    from_ref=f"build:{build_number}",
                    to_ref=f"deployment:{dep_id or env or build_number}",
                    commit_sha=commit_sha,
                    build_number=build_number,
                    deployment_id=dep_id,
                    environment=env,
                )
            )
        elif commit_sha:
            links.append(
                InvestigationCorrelation(
                    relation="commit_to_build",
                    from_ref=f"commit:{commit_sha[:12]}",
                    to_ref=f"deployment:{dep_id or env}",
                    commit_sha=commit_sha,
                    deployment_id=dep_id,
                    environment=env,
                )
            )
    return links


def _collect_commit_shas(context: UnifiedInvestigationContext) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for commit in context.commits:
        sha = ""
        if isinstance(commit, McpCommit):
            sha = (commit.sha or "").strip()
        elif isinstance(commit, McpGitLabCommit):
            sha = (commit.id or "").strip()
        if sha and sha not in seen:
            seen.add(sha)
            out.append(sha)
    for build in context.build_events:
        sha = (build.commit_sha or "").strip()
        if sha and sha not in seen:
            seen.add(sha)
            out.append(sha)
    return out


def _pr_by_merge_sha(context: UnifiedInvestigationContext) -> dict[str, McpPullRequest]:
    out: dict[str, McpPullRequest] = {}
    for pr in context.pull_requests:
        if not pr.merged:
            continue
        for commit in context.commits:
            if not isinstance(commit, McpCommit):
                continue
            msg = (commit.message or "").lower()
            title = (pr.title or "").lower()
            if pr.number and f"#{pr.number}" in msg:
                out[commit.sha] = pr
            elif title and title[:40] in msg:
                out[commit.sha] = pr
    return out


def _deployment_fields(dep: DeploymentEvent | McpDeploymentEvent) -> tuple[str, str, int | None, str]:
    if isinstance(dep, DeploymentEvent):
        return (
            dep.environment,
            dep.commit_sha,
            dep.build_number,
            dep.deployment_id,
        )
    return (
        dep.environment,
        dep.commit_sha,
        None,
        dep.environment or dep.commit_sha[:12] if dep.commit_sha else "",
    )
