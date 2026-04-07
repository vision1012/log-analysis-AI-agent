"""JIRA integration layer: fetch, normalize, and extract deterministic hints."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from schemas.jira import JiraExtractedHints, JiraNormalizedTicket, JiraTicketFetchResponse

logger = logging.getLogger(__name__)

_TICKET_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_JIRA_MARKUP_RE = re.compile(r"\{[^{}]+\}")
_WIKI_LINK_RE = re.compile(r"\[([^\]|]+)(?:\|[^\]]+)?\]")


class JiraError(Exception):
    """Base class for JIRA integration errors."""


class JiraInvalidTicketKeyError(JiraError):
    """Raised when ticket key is syntactically invalid."""


class JiraConfigError(JiraError):
    """Raised when required JIRA configuration is missing."""


class JiraAuthError(JiraError):
    """Raised when JIRA authentication fails."""


class JiraNotFoundError(JiraError):
    """Raised when JIRA ticket is not found."""


class JiraExternalApiError(JiraError):
    """Raised when JIRA API request fails unexpectedly."""


def fetch_ticket_context(ticket_key: str) -> JiraTicketFetchResponse:
    """Fetch JIRA issue by key and return normalized ticket context + hints."""
    normalized_key = _normalize_ticket_key(ticket_key)
    logger.info("jira.ticket_fetch.start ticket_key=%s", normalized_key)
    cfg = _jira_config_from_env()
    try:
        raw_issue = _fetch_issue_from_jira(cfg, normalized_key)
        ticket = _normalize_issue(raw_issue, cfg["base_url"])
        hints = _extract_hints(ticket.cleaned_text_body, ticket.labels)
        logger.info(
            "jira.ticket_fetch.success ticket_key=%s status=%s labels=%d",
            ticket.ticket_key,
            ticket.status or "",
            len(ticket.labels),
        )
        return JiraTicketFetchResponse(ticket=ticket, hints=hints)
    except JiraError:
        logger.warning("jira.ticket_fetch.failure ticket_key=%s", normalized_key)
        raise


def _normalize_ticket_key(ticket_key: str) -> str:
    key = (ticket_key or "").strip().upper()
    if not _TICKET_KEY_RE.fullmatch(key):
        raise JiraInvalidTicketKeyError("ticket key must match format PROJECT-123")
    return key


def _jira_config_from_env() -> dict[str, str]:
    base_url = os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "").strip()
    api_token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if not base_url or not email or not api_token:
        raise JiraConfigError("JIRA config missing: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN")
    return {"base_url": base_url, "email": email, "api_token": api_token}


def _fetch_issue_from_jira(cfg: dict[str, str], ticket_key: str) -> dict[str, Any]:
    fields = "summary,description,comment,status,priority,labels,created,updated"
    issue_url = f"{cfg['base_url']}/rest/api/3/issue/{parse.quote(ticket_key)}?fields={fields}"
    auth_raw = f"{cfg['email']}:{cfg['api_token']}".encode("utf-8")
    auth_header = base64.b64encode(auth_raw).decode("ascii")

    req = request.Request(
        issue_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {auth_header}",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload)
    except urlerror.HTTPError as exc:
        body = _safe_read_error_body(exc)
        if exc.code in (401, 403):
            raise JiraAuthError("JIRA authentication failed") from exc
        if exc.code == 404:
            raise JiraNotFoundError(f"ticket not found: {ticket_key}") from exc
        raise JiraExternalApiError(f"JIRA API error ({exc.code}): {body}") from exc
    except urlerror.URLError as exc:
        raise JiraExternalApiError(f"JIRA API connection error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise JiraExternalApiError("invalid JSON response from JIRA API") from exc


def _safe_read_error_body(exc: urlerror.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8")[:500]
    except Exception:
        return ""


def _normalize_issue(issue: dict[str, Any], jira_base_url: str) -> JiraNormalizedTicket:
    fields = issue.get("fields") or {}
    key = (issue.get("key") or "").strip()

    summary = _clean_text(fields.get("summary") or "")
    description = _flatten_rich_text(fields.get("description"))
    comments_text = _flatten_comments(fields.get("comment"))
    cleaned_text_body = _join_non_empty([summary, description, comments_text], sep="\n\n")

    labels_raw = fields.get("labels") or []
    labels = [str(x).strip() for x in labels_raw if str(x).strip()]
    status_name = _read_nested_str(fields, ["status", "name"])
    priority_name = _read_nested_str(fields, ["priority", "name"])

    return JiraNormalizedTicket(
        ticket_id=_none_if_empty(str(issue.get("id", "")).strip()),
        ticket_key=key,
        summary=summary,
        description=description,
        comments_text=comments_text,
        status=status_name,
        priority=priority_name,
        labels=labels,
        created_at=_none_if_empty(str(fields.get("created", "")).strip()),
        updated_at=_none_if_empty(str(fields.get("updated", "")).strip()),
        url=f"{jira_base_url}/browse/{key}" if key else f"{jira_base_url}/browse",
        cleaned_text_body=cleaned_text_body,
    )


def _read_nested_str(obj: dict[str, Any], path: list[str]) -> str | None:
    cur: Any = obj
    for part in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    out = _clean_text(str(cur)) if cur is not None else ""
    return out or None


def _flatten_comments(comment_obj: Any) -> str:
    if not isinstance(comment_obj, dict):
        return ""
    comments = comment_obj.get("comments") or []
    flattened: list[str] = []
    for c in comments:
        if not isinstance(c, dict):
            continue
        body = _flatten_rich_text(c.get("body"))
        if body:
            flattened.append(body)
    return _join_non_empty(flattened, sep="\n\n")


def _flatten_rich_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, dict):
        # JIRA ADF format usually has nested `content` lists with text nodes.
        out = _flatten_adf_node(value)
        return _clean_text(out)
    if isinstance(value, list):
        out = " ".join(_flatten_rich_text(x) for x in value)
        return _clean_text(out)
    return _clean_text(str(value))


def _flatten_adf_node(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_flatten_adf_node(x) for x in node if x is not None)
    if not isinstance(node, dict):
        return ""

    node_type = str(node.get("type") or "")
    if node_type == "hardBreak":
        return "\n"
    if "text" in node and isinstance(node.get("text"), str):
        return node["text"]

    content = node.get("content")
    if isinstance(content, list):
        return " ".join(_flatten_adf_node(x) for x in content if x is not None)
    return ""


def _clean_text(text: str) -> str:
    if not text:
        return ""
    out = text.replace("\r", "\n")
    out = _HTML_TAG_RE.sub(" ", out)
    out = _JIRA_MARKUP_RE.sub(" ", out)
    out = _WIKI_LINK_RE.sub(r"\1", out)
    out = _WHITESPACE_RE.sub(" ", out)
    return out.strip()


def _join_non_empty(parts: list[str], sep: str) -> str:
    return sep.join([p for p in parts if p])


def _none_if_empty(value: str) -> str | None:
    return value if value else None


def _extract_hints(text: str, labels: list[str]) -> JiraExtractedHints:
    lower = text.lower()
    services = _uniq(
        re.findall(
            r"\b([a-z0-9][a-z0-9_-]*(?:service|svc|api|worker|backend|frontend))\b",
            lower,
        )
    )
    envs = _uniq(
        [
            env
            for env in ["prod", "production", "staging", "stage", "dev", "qa", "test", "uat", "sandbox"]
            if re.search(rf"\b{re.escape(env)}\b", lower)
        ]
    )

    unix_paths = re.findall(r"(?:/[A-Za-z0-9._-]+)+", text)
    win_paths = re.findall(r"[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+", text)
    file_paths = _uniq(unix_paths + win_paths)

    keyword_bank = [
        "error",
        "exception",
        "timeout",
        "failed",
        "failure",
        "stacktrace",
        "panic",
        "nullpointer",
        "outofmemory",
        "oom",
        "connection refused",
        "503",
        "502",
        "504",
    ]
    error_keywords = _uniq([k for k in keyword_bank if k in lower])

    return JiraExtractedHints(
        service_names=services,
        environment_names=envs,
        file_paths=file_paths,
        error_keywords=error_keywords,
        labels=_uniq([lbl.strip() for lbl in labels if lbl.strip()]),
    )


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
