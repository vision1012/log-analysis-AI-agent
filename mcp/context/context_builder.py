"""Build and merge unified MCP investigation context."""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.common import SourceMetadata
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.gitlab_models import McpDeploymentEvent, McpGitLabCommit, McpMergeRequest, McpPipeline
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.jira_models import McpTicketContext
from schemas.jira import JiraExtractedHints


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def empty_context() -> UnifiedInvestigationContext:
    return UnifiedInvestigationContext()


def merge_context(
    base: UnifiedInvestigationContext,
    *,
    ticket_context: McpTicketContext | None = None,
    commits: list | None = None,
    pull_requests: list[McpPullRequest] | None = None,
    merge_requests: list[McpMergeRequest] | None = None,
    build_events: list[BuildEvent] | None = None,
    deployment_events: list[McpDeploymentEvent] | None = None,
    jenkins_deployment_events: list[DeploymentEvent] | None = None,
    pipelines: list[McpPipeline] | None = None,
    source_metadata: SourceMetadata | None = None,
) -> UnifiedInvestigationContext:
    """Return a new context with provider slices merged in."""
    data = base.model_dump()
    if ticket_context is not None:
        data["ticket_context"] = ticket_context.model_dump()
    if commits:
        data["commits"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in commits]
    if pull_requests:
        data["pull_requests"] = [p.model_dump() for p in pull_requests]
    if merge_requests:
        data["merge_requests"] = [m.model_dump() for m in merge_requests]
    if build_events:
        data["build_events"] = [b.model_dump() for b in build_events]
    merged_deployments = list(data.get("deployment_events") or [])
    if deployment_events:
        merged_deployments.extend([d.model_dump() for d in deployment_events])
    if jenkins_deployment_events:
        merged_deployments.extend([d.model_dump() for d in jenkins_deployment_events])
    if merged_deployments != list(data.get("deployment_events") or []):
        data["deployment_events"] = merged_deployments
    if pipelines:
        data["pipelines"] = [p.model_dump() for p in pipelines]
    if source_metadata is not None:
        meta = list(data.get("source_metadata") or [])
        meta.append(source_metadata.model_dump())
        data["source_metadata"] = meta
    return UnifiedInvestigationContext.model_validate(data)


def enrich_ticket_hints(
    hints: JiraExtractedHints,
    context: UnifiedInvestigationContext,
) -> JiraExtractedHints:
    """
    Enrich deterministic ticket hints from normalized MCP context.

    Does not replace existing hints — only augments file paths, keywords, labels.
    """
    file_paths = list(hints.file_paths)
    error_keywords = list(hints.error_keywords)
    labels = list(hints.labels)
    service_names = list(hints.service_names)

    ticket = context.ticket_context
    if ticket:
        labels = _uniq(labels + ticket.labels)
        for comment in ticket.comments:
            error_keywords = _uniq(error_keywords + _keyword_hits(comment.body))
        for linked in ticket.linked_issues:
            error_keywords = _uniq(error_keywords + _keyword_hits(linked.summary))

    for pr in context.pull_requests:
        file_paths = _uniq(file_paths + pr.changed_files)
        error_keywords = _uniq(error_keywords + _keyword_hits(pr.title))

    for commit in context.commits:
        if isinstance(commit, McpCommit):
            file_paths = _uniq(file_paths + commit.changed_files)
            error_keywords = _uniq(error_keywords + _keyword_hits(commit.message))
        elif isinstance(commit, McpGitLabCommit):
            error_keywords = _uniq(error_keywords + _keyword_hits(commit.title))

    for dep in context.deployment_events:
        env = getattr(dep, "environment", "") or ""
        if env:
            envs = list(hints.environment_names)
            if env not in envs:
                envs.append(env)
            hints = hints.model_copy(update={"environment_names": envs})

    return hints.model_copy(
        update={
            "file_paths": file_paths[:100],
            "error_keywords": error_keywords[:50],
            "labels": labels[:50],
            "service_names": service_names,
        }
    )


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = (item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


_KEYWORD_BANK = ("error", "exception", "timeout", "failed", "panic", "outage", "rollback")


def _keyword_hits(text: str) -> list[str]:
    lower = (text or "").lower()
    return [k for k in _KEYWORD_BANK if k in lower]
