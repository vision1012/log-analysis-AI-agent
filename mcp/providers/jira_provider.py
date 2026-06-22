"""JIRA MCP provider — normalized ticket context for investigations."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from api.services.jira_service import (
    JiraAuthError,
    JiraConfigError,
    JiraError,
    JiraNotFoundError,
    fetch_ticket_context,
)
from mcp.config import MCPFetchParams, jira_mcp_enabled
from mcp.context.context_builder import merge_context
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.providers.base import BaseMCPProvider
from mcp.schemas.common import ProviderHealth, SourceMetadata
from mcp.schemas.jira_models import McpJiraComment, McpLinkedIssue, McpTicketContext

logger = logging.getLogger(__name__)

_TICKET_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


class JiraProvider(BaseMCPProvider):
    source = "jira"

    def is_enabled(self) -> bool:
        return jira_mcp_enabled()

    def is_configured(self) -> bool:
        try:
            _jira_cfg()
            return True
        except JiraConfigError:
            return False

    def health_check(self) -> ProviderHealth:
        enabled = self.is_enabled()
        configured = self.is_configured()
        if not enabled:
            return ProviderHealth(
                source="jira", enabled=False, configured=configured, reachable=False, detail="disabled"
            )
        if not configured:
            return ProviderHealth(
                source="jira", enabled=True, configured=False, reachable=False, detail="missing JIRA config"
            )
        try:
            cfg = _jira_cfg()
            _jira_get_json(cfg, "/rest/api/3/myself")
            return ProviderHealth(source="jira", enabled=True, configured=True, reachable=True, detail="ok")
        except Exception as exc:
            return ProviderHealth(
                source="jira", enabled=True, configured=True, reachable=False, detail=str(exc)[:200]
            )

    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        key = (params.ticket_key or "").strip().upper()
        if not key or key == "UNKNOWN" or not _TICKET_KEY_RE.fullmatch(key):
            return UnifiedInvestigationContext()

        fetched = fetch_ticket_context(key)
        ticket = fetched.ticket
        raw_issue = _fetch_issue_with_links(key)
        comments = _parse_comments(raw_issue)
        linked = _parse_linked_issues(raw_issue)

        ticket_ctx = McpTicketContext(
            issue_key=ticket.ticket_key,
            summary=ticket.summary,
            description=ticket.description,
            status=ticket.status,
            priority=ticket.priority,
            labels=list(ticket.labels),
            comments=comments,
            linked_issues=linked,
            url=ticket.url,
        )
        meta = SourceMetadata(
            source="jira",
            fetched_at=datetime.now(timezone.utc),
            ok=True,
            detail=f"ticket={key}",
        )
        return merge_context(
            UnifiedInvestigationContext(),
            ticket_context=ticket_ctx,
            source_metadata=meta,
        )


def _jira_cfg() -> dict[str, str]:
    base_url = os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "").strip()
    api_token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if not base_url or not email or not api_token:
        raise JiraConfigError("JIRA config missing")
    return {"base_url": base_url, "email": email, "api_token": api_token}


def _auth_header(cfg: dict[str, str]) -> str:
    raw = f"{cfg['email']}:{cfg['api_token']}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _jira_get_json(cfg: dict[str, str], path: str) -> dict[str, Any]:
    url = f"{cfg['base_url']}{path}"
    req = request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": _auth_header(cfg)},
        method="GET",
    )
    timeout = int(os.environ.get("JIRA_TIMEOUT_SEC", "15"))
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        if exc.code in (401, 403):
            raise JiraAuthError("JIRA authentication failed") from exc
        if exc.code == 404:
            raise JiraNotFoundError("not found") from exc
        raise JiraError(f"JIRA HTTP {exc.code}") from exc


def _fetch_issue_with_links(ticket_key: str) -> dict[str, Any]:
    cfg = _jira_cfg()
    fields = parse.quote(
        "summary,description,comment,status,priority,labels,created,updated,issuelinks"
    )
    return _jira_get_json(cfg, f"/rest/api/3/issue/{parse.quote(ticket_key)}?fields={fields}")


def _parse_comments(issue: dict[str, Any]) -> list[McpJiraComment]:
    fields = issue.get("fields") or {}
    comment_obj = fields.get("comment") or {}
    comments = comment_obj.get("comments") or []
    out: list[McpJiraComment] = []
    for c in comments:
        if not isinstance(c, dict):
            continue
        author = ""
        author_obj = c.get("author")
        if isinstance(author_obj, dict):
            author = str(author_obj.get("displayName") or author_obj.get("emailAddress") or "")
        body = _plain_text(c.get("body"))
        out.append(
            McpJiraComment(
                author=author,
                body=body,
                created_at=str(c.get("created") or "") or None,
            )
        )
    return out


def _parse_linked_issues(issue: dict[str, Any]) -> list[McpLinkedIssue]:
    fields = issue.get("fields") or {}
    links = fields.get("issuelinks") or []
    out: list[McpLinkedIssue] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        link_type = ""
        lt = link.get("type")
        if isinstance(lt, dict):
            link_type = str(lt.get("name") or lt.get("outward") or "")
        inward = link.get("inwardIssue")
        outward = link.get("outwardIssue")
        for side, issue_obj in (("inward", inward), ("outward", outward)):
            if not isinstance(issue_obj, dict):
                continue
            key = str(issue_obj.get("key") or "")
            if not key:
                continue
            f = issue_obj.get("fields") or {}
            status = None
            st = f.get("status")
            if isinstance(st, dict):
                status = str(st.get("name") or "") or None
            out.append(
                McpLinkedIssue(
                    issue_key=key,
                    link_type=f"{link_type}:{side}" if link_type else side,
                    summary=str(f.get("summary") or ""),
                    status=status,
                )
            )
    return out


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts: list[str] = []
        content = value.get("content")
        if isinstance(content, list):
            for node in content:
                if isinstance(node, dict) and isinstance(node.get("text"), str):
                    parts.append(node["text"])
        return " ".join(parts).strip()
    return str(value).strip()
