"""GitHub MCP provider — commits and pull requests."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from mcp.config import MCPFetchParams, github_lookback_days, github_mcp_enabled
from mcp.context.context_builder import merge_context
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.providers.base import BaseMCPProvider
from mcp.runtime_connection import ProviderRuntimeConnection
from mcp.schemas.common import ProviderHealth, SourceMetadata
from mcp.schemas.github_models import McpCommit, McpPullRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _GitHubClientConfig:
    token: str
    api_base: str
    owner: str
    repo: str
    connection_id: str = ""


class GitHubProvider(BaseMCPProvider):
    source = "github"

    def is_enabled(self) -> bool:
        return github_mcp_enabled()

    def is_configured(self) -> bool:
        try:
            _github_client_config(
                self._runtime_connection,
                MCPFetchParams(ticket_key=""),
                database_only=self._database_only,
            )
            return True
        except RuntimeError:
            return False

    def health_check(self) -> ProviderHealth:
        enabled = self.is_enabled()
        configured = self.is_configured()
        if not enabled:
            return ProviderHealth(
                source="github", enabled=False, configured=configured, reachable=False, detail="disabled"
            )
        if not configured:
            detail = "no integration connection configured"
            if not self._database_only:
                detail = "missing GITHUB_TOKEN or repo"
            return ProviderHealth(
                source="github",
                enabled=True,
                configured=False,
                reachable=False,
                detail=detail,
            )
        try:
            client = _github_client_config(
                self._runtime_connection,
                MCPFetchParams(ticket_key=""),
                database_only=self._database_only,
            )
            _github_get("/user", client=client)
            detail = "ok"
            if client.connection_id:
                detail = f"ok:connection={client.connection_id}"
            return ProviderHealth(source="github", enabled=True, configured=True, reachable=True, detail=detail)
        except Exception as exc:
            return ProviderHealth(
                source="github", enabled=True, configured=True, reachable=False, detail=str(exc)[:200]
            )

    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        try:
            client = _github_client_config(
                self._runtime_connection,
                params,
                database_only=self._database_only,
            )
        except RuntimeError:
            return UnifiedInvestigationContext()

        since, until = _resolve_github_fetch_window(params)

        commits = _fetch_commits(client, since=since, until=until)
        prs = _fetch_pull_requests(client, since=since, until=until)

        detail = f"repo={client.owner}/{client.repo} commits={len(commits)} prs={len(prs)}"
        if client.connection_id:
            detail = f"{detail} connection={client.connection_id}"
        meta = SourceMetadata(
            source="github",
            fetched_at=datetime.now(timezone.utc),
            ok=True,
            detail=detail,
        )
        return merge_context(
            UnifiedInvestigationContext(),
            commits=commits,
            pull_requests=prs,
            source_metadata=meta,
        )


def _github_token(runtime: ProviderRuntimeConnection | None, *, database_only: bool = False) -> str:
    if runtime is not None and runtime.source == "database":
        token = str((runtime.credentials or {}).get("token") or "").strip()
        if token:
            return token
        if database_only:
            return ""
    if database_only:
        return ""
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_API_TOKEN") or "").strip()


def _github_api_base() -> str:
    return (os.environ.get("GITHUB_API_BASE") or "https://api.github.com").strip().rstrip("/")


def _default_owner_repo() -> tuple[str, str]:
    raw = (os.environ.get("GITHUB_REPO") or os.environ.get("MCP_DEFAULT_REPO") or "").strip()
    return _split_repo(raw)


def _split_repo(repo_name: str) -> tuple[str, str]:
    s = (repo_name or "").strip().strip("/")
    if "/" not in s:
        return "", ""
    owner, repo = s.split("/", 1)
    return owner.strip(), repo.strip()


def _resolve_repo_from_runtime(runtime: ProviderRuntimeConnection) -> tuple[str, str]:
    org = (runtime.org_name or "").strip()
    repo_field = (runtime.repo_name or "").strip()
    if repo_field and "/" in repo_field:
        return _split_repo(repo_field)
    if org and repo_field:
        return org, repo_field
    if repo_field:
        return _split_repo(repo_field)
    return "", ""


def _resolve_repo(params: MCPFetchParams) -> tuple[str, str]:
    explicit = _split_repo(params.resolved_repo_name())
    if explicit[0] and explicit[1]:
        return explicit
    return _default_owner_repo()


def _github_client_config(
    runtime: ProviderRuntimeConnection | None,
    params: MCPFetchParams,
    *,
    database_only: bool = False,
) -> _GitHubClientConfig:
    token = _github_token(runtime, database_only=database_only)
    if not token:
        if database_only:
            raise RuntimeError("integration connection missing GitHub token")
        raise RuntimeError("GITHUB_TOKEN not set")
    owner, repo = "", ""
    connection_id = ""
    if runtime is not None and runtime.source == "database":
        owner, repo = _resolve_repo_from_runtime(runtime)
        connection_id = runtime.connection_id
    if not owner or not repo:
        if database_only:
            raise RuntimeError("integration connection missing GitHub org/repo")
        owner, repo = _resolve_repo(params)
    if not owner or not repo:
        raise RuntimeError("GitHub repo not configured")
    return _GitHubClientConfig(
        token=token,
        api_base=_github_api_base(),
        owner=owner,
        repo=repo,
        connection_id=connection_id,
    )


def _parse_iso(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_github_fetch_window(params: MCPFetchParams) -> tuple[str | None, str | None]:
    """
    Resolve GitHub commit/PR fetch bounds.

    When investigation times are present (e.g. from log parsing), widen the window
    to ``MCP_GITHUB_LOOKBACK_DAYS`` before the anchor instead of using the raw
    narrow log span. When no times are set, preserve unbounded fetch (API page cap).
    """
    start_raw = (params.start_time or "").strip() or None
    end_raw = (params.end_time or "").strip() or None
    if not start_raw and not end_raw:
        return None, None

    anchor = _parse_iso(end_raw) or _parse_iso(start_raw) or datetime.now(timezone.utc)
    lookback_days = github_lookback_days()
    since = _iso_z(anchor - timedelta(days=lookback_days))
    until = _iso_z(_parse_iso(end_raw) or anchor)
    return since, until


def _github_get(path: str, *, client: _GitHubClientConfig, query: dict[str, str] | None = None) -> Any:
    q = ""
    if query:
        q = "?" + parse.urlencode({k: v for k, v in query.items() if v})
    url = f"{client.api_base}{path}{q}"
    req = request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {client.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    timeout = int(os.environ.get("GITHUB_TIMEOUT_SEC", "15"))
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_commits(
    client: _GitHubClientConfig,
    *,
    since: str | None,
    until: str | None,
) -> list[McpCommit]:
    query: dict[str, str] = {"per_page": "30"}
    if since:
        query["since"] = since
    if until:
        query["until"] = until
    try:
        payload = _github_get(f"/repos/{client.owner}/{client.repo}/commits", client=client, query=query)
    except urlerror.HTTPError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[McpCommit] = []
    for item in payload[:30]:
        if not isinstance(item, dict):
            continue
        sha = str(item.get("sha") or "")
        commit_obj = item.get("commit") or {}
        message = str(commit_obj.get("message") or "")
        author = ""
        author_obj = commit_obj.get("author") or {}
        if isinstance(author_obj, dict):
            author = str(author_obj.get("name") or author_obj.get("email") or "")
        committed_at = str(commit_obj.get("author", {}).get("date") or "") or None
        changed_files: list[str] = []
        if sha:
            try:
                detail = _github_get(f"/repos/{client.owner}/{client.repo}/commits/{sha}", client=client)
                files = detail.get("files") if isinstance(detail, dict) else []
                if isinstance(files, list):
                    changed_files = [str(f.get("filename") or "") for f in files if isinstance(f, dict) and f.get("filename")]
            except Exception:
                pass
        out.append(
            McpCommit(
                sha=sha,
                message=message,
                author=author,
                committed_at=committed_at,
                changed_files=changed_files[:50],
            )
        )
    return out


def _pr_activity_time(pr: dict[str, Any]) -> datetime | None:
    """Latest activity timestamp for lookback filtering (merged > updated > created)."""
    times: list[datetime] = []
    for key in ("merged_at", "updated_at", "created_at"):
        dt = _parse_iso(str(pr.get(key) or ""))
        if dt is not None:
            times.append(dt)
    return max(times) if times else None


def _pr_within_lookback(
    pr: dict[str, Any],
    *,
    since: str | None,
    until: str | None,
) -> bool:
    """
    Keep PRs whose merged/updated activity falls in the investigation lookback.

    Uses merged_at and updated_at instead of a strict created_at upper bound so PRs
    opened before the log window but merged/updated during lookback are retained.
    No upper-bound filter on created_at — PRs updated after the log window may still
    touch the candidate path.
    """
    _ = until
    activity = _pr_activity_time(pr)
    if activity is None:
        return True
    since_dt = _parse_iso(since)
    if since_dt and activity < since_dt:
        return False
    return True


def _fetch_pull_request_changed_files(
    client: _GitHubClientConfig,
    number: int,
) -> list[str]:
    if not number:
        return []
    try:
        files_payload = _github_get(
            f"/repos/{client.owner}/{client.repo}/pulls/{number}/files",
            client=client,
            query={"per_page": "100"},
        )
    except Exception:
        return []
    if not isinstance(files_payload, list):
        return []
    return [
        str(f.get("filename") or "")
        for f in files_payload
        if isinstance(f, dict) and f.get("filename")
    ]


def _fetch_pull_requests(
    client: _GitHubClientConfig,
    *,
    since: str | None,
    until: str | None = None,
) -> list[McpPullRequest]:
    try:
        payload = _github_get(
            f"/repos/{client.owner}/{client.repo}/pulls",
            client=client,
            query={"state": "all", "per_page": "30", "sort": "updated", "direction": "desc"},
        )
    except urlerror.HTTPError:
        return []
    if not isinstance(payload, list):
        return []
    before_filter = len(payload)
    out: list[McpPullRequest] = []
    for pr in payload[:30]:
        if not isinstance(pr, dict):
            continue
        if not _pr_within_lookback(pr, since=since, until=until):
            continue
        created = str(pr.get("created_at") or "")
        number = int(pr.get("number") or 0)
        merged_at = str(pr.get("merged_at") or "") or None
        changed_files = _fetch_pull_request_changed_files(client, number)
        out.append(
            McpPullRequest(
                number=number,
                title=str(pr.get("title") or ""),
                state=str(pr.get("state") or ""),
                merged=bool(pr.get("merged_at")),
                author=str((pr.get("user") or {}).get("login") or ""),
                created_at=created or None,
                merged_at=merged_at,
                changed_files=changed_files[:100],
                url=str(pr.get("html_url") or ""),
            )
        )
    logger.info(
        "github.pr_fetch repo=%s/%s before_filter=%d after_filter=%d since=%s until=%s",
        client.owner,
        client.repo,
        before_filter,
        len(out),
        since,
        until,
    )
    for pr in out[:5]:
        logger.info(
            "github.pr_fetch item number=%s changed_files=%d title=%s",
            pr.number,
            len(pr.changed_files or []),
            (pr.title or "")[:80],
        )
    return out
