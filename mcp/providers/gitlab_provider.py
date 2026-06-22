"""GitLab MCP provider — commits, merge requests, pipelines, deployments."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from mcp.config import MCPFetchParams, gitlab_mcp_enabled
from mcp.context.context_builder import merge_context
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.providers.base import BaseMCPProvider
from mcp.schemas.common import ProviderHealth, SourceMetadata
from mcp.schemas.gitlab_models import McpDeploymentEvent, McpGitLabCommit, McpMergeRequest, McpPipeline

logger = logging.getLogger(__name__)


class GitLabProvider(BaseMCPProvider):
    source = "gitlab"

    def is_enabled(self) -> bool:
        return gitlab_mcp_enabled()

    def is_configured(self) -> bool:
        return bool(_gitlab_token()) and bool(_resolve_project_id(""))

    def health_check(self) -> ProviderHealth:
        enabled = self.is_enabled()
        configured = self.is_configured()
        if not enabled:
            return ProviderHealth(
                source="gitlab", enabled=False, configured=configured, reachable=False, detail="disabled"
            )
        if not configured:
            return ProviderHealth(
                source="gitlab",
                enabled=True,
                configured=False,
                reachable=False,
                detail="missing GITLAB_TOKEN or GITLAB_PROJECT_ID",
            )
        try:
            _gitlab_get("/user")
            return ProviderHealth(source="gitlab", enabled=True, configured=True, reachable=True, detail="ok")
        except Exception as exc:
            return ProviderHealth(
                source="gitlab", enabled=True, configured=True, reachable=False, detail=str(exc)[:200]
            )

    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        project_id = _resolve_project_id(params.resolved_gitlab_project())
        if not project_id:
            return UnifiedInvestigationContext()

        since = (params.start_time or "").strip() or None
        until = (params.end_time or "").strip() or None

        commits = _fetch_commits(project_id, since=since, until=until)
        mrs = _fetch_merge_requests(project_id, since=since)
        pipelines = _fetch_pipelines(project_id)
        deployments = _fetch_deployments(project_id)

        meta = SourceMetadata(
            source="gitlab",
            fetched_at=datetime.now(timezone.utc),
            ok=True,
            detail=f"project={project_id} commits={len(commits)} mrs={len(mrs)}",
        )
        return merge_context(
            UnifiedInvestigationContext(),
            commits=commits,
            merge_requests=mrs,
            pipelines=pipelines,
            deployment_events=deployments,
            source_metadata=meta,
        )


def _gitlab_token() -> str:
    return (os.environ.get("GITLAB_TOKEN") or os.environ.get("GITLAB_PRIVATE_TOKEN") or "").strip()


def _gitlab_base() -> str:
    return (os.environ.get("GITLAB_BASE_URL") or "https://gitlab.com").strip().rstrip("/")


def _resolve_project_id(explicit: str) -> str:
    pid = (explicit or os.environ.get("GITLAB_PROJECT_ID") or "").strip()
    if pid:
        return parse.quote(pid, safe="")
    repo = (os.environ.get("GITLAB_REPO") or os.environ.get("MCP_DEFAULT_REPO") or "").strip()
    if "/" in repo:
        return parse.quote(repo, safe="")
    return ""


def _gitlab_get(path: str, query: dict[str, str] | None = None) -> Any:
    token = _gitlab_token()
    if not token:
        raise RuntimeError("GITLAB_TOKEN not set")
    q = ""
    if query:
        q = "?" + parse.urlencode({k: v for k, v in query.items() if v})
    url = f"{_gitlab_base()}/api/v4{path}{q}"
    req = request.Request(
        url,
        headers={"PRIVATE-TOKEN": token, "Accept": "application/json"},
        method="GET",
    )
    timeout = int(os.environ.get("GITLAB_TIMEOUT_SEC", "15"))
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_commits(
    project_id: str,
    *,
    since: str | None,
    until: str | None,
) -> list[McpGitLabCommit]:
    query: dict[str, str] = {"per_page": "30"}
    if since:
        query["since"] = since
    if until:
        query["until"] = until
    try:
        payload = _gitlab_get(f"/projects/{project_id}/repository/commits", query)
    except urlerror.HTTPError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[McpGitLabCommit] = []
    for item in payload[:30]:
        if not isinstance(item, dict):
            continue
        out.append(
            McpGitLabCommit(
                id=str(item.get("id") or ""),
                short_id=str(item.get("short_id") or ""),
                title=str(item.get("title") or item.get("message") or ""),
                author=str((item.get("author_name") or "")),
                committed_at=str(item.get("committed_date") or item.get("created_at") or "") or None,
            )
        )
    return out


def _fetch_merge_requests(project_id: str, *, since: str | None) -> list[McpMergeRequest]:
    try:
        payload = _gitlab_get(
            f"/projects/{project_id}/merge_requests",
            {"state": "all", "per_page": "30", "order_by": "updated_at", "sort": "desc"},
        )
    except urlerror.HTTPError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[McpMergeRequest] = []
    for mr in payload[:30]:
        if not isinstance(mr, dict):
            continue
        created = str(mr.get("created_at") or "")
        if since and created and created < since:
            continue
        out.append(
            McpMergeRequest(
                iid=int(mr.get("iid") or 0),
                title=str(mr.get("title") or ""),
                state=str(mr.get("state") or ""),
                author=str((mr.get("author") or {}).get("username") or ""),
                created_at=created or None,
                merged_at=str(mr.get("merged_at") or "") or None,
                url=str(mr.get("web_url") or ""),
            )
        )
    return out


def _fetch_pipelines(project_id: str) -> list[McpPipeline]:
    try:
        payload = _gitlab_get(f"/projects/{project_id}/pipelines", {"per_page": "20", "order_by": "id", "sort": "desc"})
    except urlerror.HTTPError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[McpPipeline] = []
    for p in payload[:20]:
        if not isinstance(p, dict):
            continue
        out.append(
            McpPipeline(
                id=int(p.get("id") or 0),
                status=str(p.get("status") or ""),
                ref=str(p.get("ref") or ""),
                created_at=str(p.get("created_at") or "") or None,
                finished_at=str(p.get("updated_at") or "") or None,
                url=str(p.get("web_url") or ""),
            )
        )
    return out


def _fetch_deployments(project_id: str) -> list[McpDeploymentEvent]:
    try:
        payload = _gitlab_get(f"/projects/{project_id}/deployments", {"per_page": "20", "order_by": "id", "sort": "desc"})
    except urlerror.HTTPError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[McpDeploymentEvent] = []
    for d in payload[:20]:
        if not isinstance(d, dict):
            continue
        env = d.get("environment") or {}
        env_name = str(env.get("name") or "") if isinstance(env, dict) else ""
        deployable = d.get("deployable") or {}
        commit_sha = ""
        if isinstance(deployable, dict):
            commit_sha = str((deployable.get("commit") or {}).get("id") or "")
        out.append(
            McpDeploymentEvent(
                environment=env_name,
                status=str(d.get("status") or ""),
                deployed_at=str(d.get("created_at") or "") or None,
                commit_sha=commit_sha,
                url=str(d.get("web_url") or ""),
            )
        )
    return out
