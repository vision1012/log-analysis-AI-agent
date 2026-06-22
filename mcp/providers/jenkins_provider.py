"""Jenkins MCP provider — normalized build and deployment context."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from mcp.config import MCPFetchParams, jenkins_mcp_enabled
from mcp.context.context_builder import merge_context
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.providers.base import BaseMCPProvider
from mcp.schemas.common import ProviderHealth, SourceMetadata
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent

logger = logging.getLogger(__name__)

_DEPLOY_PARAM_NAMES = frozenset(
    {"environment", "deploy_env", "deployment_environment", "target_env", "env"}
)


class JenkinsProvider(BaseMCPProvider):
    source = "jenkins"

    def is_enabled(self) -> bool:
        return jenkins_mcp_enabled()

    def is_configured(self) -> bool:
        try:
            _jenkins_cfg(allow_missing=False)
            return True
        except RuntimeError:
            return False

    def health_check(self) -> ProviderHealth:
        enabled = self.is_enabled()
        try:
            cfg = _jenkins_cfg(allow_missing=False)
            configured = True
        except RuntimeError:
            configured = False
            cfg = None

        if not enabled:
            return ProviderHealth(
                source="jenkins",
                enabled=False,
                configured=configured,
                reachable=False,
                detail="disabled",
            )
        if not configured:
            return ProviderHealth(
                source="jenkins",
                enabled=True,
                configured=False,
                reachable=False,
                detail="missing JENKINS_BASE_URL, credentials, or JENKINS_JOB_NAME",
            )
        try:
            _jenkins_get(cfg, f"{_job_api_path(cfg['job_name'])}/api/json", {"tree": "name"})
            return ProviderHealth(source="jenkins", enabled=True, configured=True, reachable=True, detail="ok")
        except Exception as exc:
            return ProviderHealth(
                source="jenkins",
                enabled=True,
                configured=True,
                reachable=False,
                detail=str(exc)[:200],
            )

    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        try:
            cfg = _jenkins_cfg(allow_missing=False)
        except RuntimeError:
            return UnifiedInvestigationContext()

        since_ms = _iso_to_epoch_ms(params.start_time)
        until_ms = _iso_to_epoch_ms(params.end_time)

        builds, deployments = _fetch_builds_and_deployments(cfg, since_ms=since_ms, until_ms=until_ms)
        meta = SourceMetadata(
            source="jenkins",
            fetched_at=datetime.now(timezone.utc),
            ok=True,
            detail=f"job={cfg['job_name']} builds={len(builds)} deployments={len(deployments)}",
        )
        return merge_context(
            UnifiedInvestigationContext(),
            build_events=builds,
            jenkins_deployment_events=deployments,
            source_metadata=meta,
        )


def _jenkins_cfg(*, allow_missing: bool) -> dict[str, str]:
    base_url = (os.environ.get("JENKINS_BASE_URL") or "").strip().rstrip("/")
    user = (os.environ.get("JENKINS_USER") or "").strip()
    token = (os.environ.get("JENKINS_API_TOKEN") or "").strip()
    job_name = (os.environ.get("JENKINS_JOB_NAME") or "").strip()
    if not base_url or not user or not token or not job_name:
        if allow_missing:
            return {}
        raise RuntimeError("Jenkins MCP config incomplete")
    return {"base_url": base_url, "user": user, "token": token, "job_name": job_name}


def _auth_header(cfg: dict[str, str]) -> str:
    raw = f"{cfg['user']}:{cfg['token']}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _job_api_path(job_name: str) -> str:
    parts = [p.strip() for p in job_name.split("/") if p.strip()]
    if not parts:
        return ""
    return "/job/" + "/job/".join(parts)


def _jenkins_get(cfg: dict[str, str], path: str, query: dict[str, str] | None = None) -> Any:
    q = ""
    if query:
        q = "?" + parse.urlencode({k: v for k, v in query.items() if v})
    url = f"{cfg['base_url']}{path}{q}"
    req = request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": _auth_header(cfg)},
        method="GET",
    )
    timeout = int(os.environ.get("JENKINS_TIMEOUT_SEC", "15"))
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_builds_and_deployments(
    cfg: dict[str, str],
    *,
    since_ms: int | None,
    until_ms: int | None,
) -> tuple[list[BuildEvent], list[DeploymentEvent]]:
    job_path = _job_api_path(cfg["job_name"])
    tree = (
        "builds[number,url,result,timestamp,duration,actions[causes[userName],"
        "lastBuiltRevision[branch[name]],parameters[name,value]],"
        "changeSet[items[commitId]]]{0,30}"
    )
    try:
        payload = _jenkins_get(cfg, f"{job_path}/api/json", {"tree": tree})
    except urlerror.HTTPError:
        return [], []

    raw_builds = payload.get("builds") if isinstance(payload, dict) else []
    if not isinstance(raw_builds, list):
        return [], []

    builds: list[BuildEvent] = []
    deployments: list[DeploymentEvent] = []
    for item in raw_builds[:30]:
        if not isinstance(item, dict):
            continue
        build_event, deploy_events = _normalize_build(item, since_ms=since_ms, until_ms=until_ms)
        if build_event is not None:
            builds.append(build_event)
            deployments.extend(deploy_events)
    return builds, deployments


def _normalize_build(
    item: dict[str, Any],
    *,
    since_ms: int | None,
    until_ms: int | None,
) -> tuple[BuildEvent | None, list[DeploymentEvent]]:
    number = int(item.get("number") or 0)
    if number <= 0:
        return None, []

    timestamp_ms = int(item.get("timestamp") or 0)
    if since_ms is not None and timestamp_ms and timestamp_ms < since_ms:
        return None, []
    if until_ms is not None and timestamp_ms and timestamp_ms > until_ms:
        return None, []

    duration_ms = int(item.get("duration") or 0)
    started_at = _epoch_ms_to_iso(timestamp_ms) if timestamp_ms else None
    completed_at = _epoch_ms_to_iso(timestamp_ms + duration_ms) if timestamp_ms and duration_ms else started_at

    branch, commit_sha, triggered_by = _parse_actions(item.get("actions") or [])
    if not commit_sha:
        commit_sha = _parse_changeset(item.get("changeSet") or {})

    build_url = str(item.get("url") or "")
    build_id = f"jenkins:{number}"

    build = BuildEvent(
        build_id=build_id,
        build_number=number,
        build_url=build_url,
        status=str(item.get("result") or "IN_PROGRESS"),
        branch=branch,
        commit_sha=commit_sha,
        started_at=started_at,
        completed_at=completed_at,
        triggered_by=triggered_by,
    )

    deployments = _extract_deployments(
        build_number=number,
        commit_sha=commit_sha,
        build_url=build_url,
        status=build.status,
        deployed_at=completed_at or started_at,
        actions=item.get("actions") or [],
    )
    return build, deployments


def _parse_actions(actions: list[Any]) -> tuple[str, str, str]:
    branch = ""
    commit_sha = ""
    triggered_by = ""
    for action in actions:
        if not isinstance(action, dict):
            continue
        causes = action.get("causes")
        if isinstance(causes, list):
            for cause in causes:
                if isinstance(cause, dict) and cause.get("userName"):
                    triggered_by = str(cause["userName"])
                    break
        revision = action.get("lastBuiltRevision")
        if isinstance(revision, dict):
            branches = revision.get("branch")
            if isinstance(branches, list) and branches:
                first = branches[0]
                if isinstance(first, dict):
                    branch = str(first.get("name") or "")
            commit_sha = str(revision.get("SHA1") or revision.get("sha1") or commit_sha)
    return branch, commit_sha, triggered_by


def _parse_changeset(change_set: dict[str, Any]) -> str:
    items = change_set.get("items")
    if not isinstance(items, list) or not items:
        return ""
    first = items[0]
    if isinstance(first, dict):
        return str(first.get("commitId") or first.get("id") or "")
    return ""


def _extract_deployments(
    *,
    build_number: int,
    commit_sha: str,
    build_url: str,
    status: str,
    deployed_at: str | None,
    actions: list[Any],
) -> list[DeploymentEvent]:
    out: list[DeploymentEvent] = []
    seen_envs: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        params = action.get("parameters")
        if not isinstance(params, list):
            continue
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip()
            if name.lower() not in _DEPLOY_PARAM_NAMES:
                continue
            environment = str(param.get("value") or "").strip()
            if not environment or environment in seen_envs:
                continue
            seen_envs.add(environment)
            out.append(
                DeploymentEvent(
                    deployment_id=f"jenkins-deploy:{build_number}:{environment}",
                    environment=environment,
                    status=status,
                    commit_sha=commit_sha,
                    build_number=build_number,
                    deployed_at=deployed_at,
                    deployment_url=build_url,
                )
            )
    return out


def _iso_to_epoch_ms(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def _epoch_ms_to_iso(epoch_ms: int) -> str:
    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")
