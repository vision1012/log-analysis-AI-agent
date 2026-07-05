"""JIRA integration layer: fetch, normalize, and extract deterministic hints."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from schemas.jira import (
    JiraExtractedHints,
    JiraNormalizedTicket,
    JiraTicketFetchResponse,
    JiraTicketSearchResponse,
    JiraTicketSearchHit,
)

logger = logging.getLogger(__name__)

_TICKET_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_JIRA_MARKUP_RE = re.compile(r"\{[^{}]+\}")
_WIKI_LINK_RE = re.compile(r"\[([^\]|]+)(?:\|[^\]]+)?\]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEFAULT_TIMEOUT_SEC = 15
_DEFAULT_MAX_RETRIES = 1


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


class JiraInvalidSearchError(JiraError):
    """Raised when search input is invalid or JIRA rejects the query."""


_MAX_SEARCH_TEXT_LEN = 200
_MAX_SEARCH_RESULTS = 50


def fetch_ticket_context(ticket_key: str, *, workspace_id: str | None = None) -> JiraTicketFetchResponse:
    """Fetch JIRA issue by key and return normalized ticket context + hints."""
    normalized_key = _normalize_ticket_key(ticket_key)
    logger.info("jira.ticket_fetch.start ticket_key=%s", normalized_key)
    cfg = _jira_config(workspace_id=workspace_id)
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
    except JiraError as exc:
        logger.warning(
            "jira.ticket_fetch.failure ticket_key=%s error_type=%s",
            normalized_key,
            type(exc).__name__,
        )
        raise


def search_tickets(
    *,
    q: str | None = None,
    jql: str | None = None,
    max_results: int = 25,
    workspace_id: str | None = None,
) -> JiraTicketSearchResponse:
    """
    Search JIRA issues via ``POST /rest/api/3/search``.

    Pass **jql** for a raw JQL query, or **q** for a simple text search (mapped to
    ``text ~ "..." ORDER BY updated DESC``). If both are set, **jql** wins.
    """
    raw_jql = (jql or "").strip()
    raw_q = (q or "").strip()

    if raw_jql:
        jql_used = raw_jql
    elif raw_q:
        if len(raw_q) > _MAX_SEARCH_TEXT_LEN:
            raise JiraInvalidSearchError(
                f"search text must be at most {_MAX_SEARCH_TEXT_LEN} characters",
            )
        escaped = _escape_jql_literal(raw_q)
        jql_used = f'text ~ "{escaped}" ORDER BY updated DESC'
    else:
        raise JiraInvalidSearchError("provide query parameter q (text) or jql")

    cfg = _jira_config(workspace_id=workspace_id)
    n = max(1, min(int(max_results), _MAX_SEARCH_RESULTS))

    logger.info(
        "jira.ticket_search.start mode=%s max_results=%d",
        "jql" if raw_jql else "text",
        n,
    )
    payload = _post_json_to_jira(
        cfg,
        "/rest/api/3/search/jql",
        {
            "jql": jql_used,
            "maxResults": n,
            "fields": ["summary", "status", "priority", "labels", "updated"],
        },
    )
    issues_raw = payload.get("issues") or []
    hits: list[JiraTicketSearchHit] = []
    for issue in issues_raw:
        if isinstance(issue, dict):
            hits.append(_issue_to_search_hit(issue))
    total = int(payload.get("total") if payload.get("total") is not None else len(hits))
    logger.info("jira.ticket_search.success returned=%d total=%d", len(hits), total)
    return JiraTicketSearchResponse(issues=hits, total=total, jql_used=jql_used)


def _escape_jql_literal(value: str) -> str:
    """Escape a string for use inside JQL double-quoted literals."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _issue_to_search_hit(issue: dict[str, Any]) -> JiraTicketSearchHit:
    fields = issue.get("fields") or {}
    key = (issue.get("key") or "").strip()
    summary = _clean_text(str(fields.get("summary") or ""))
    status_name = _read_nested_str(fields, ["status", "name"])
    priority_name = _read_nested_str(fields, ["priority", "name"])
    labels_raw = fields.get("labels") or []
    labels = [str(x).strip() for x in labels_raw if str(x).strip()]
    updated = _none_if_empty(str(fields.get("updated", "")).strip())
    return JiraTicketSearchHit(
        ticket_key=key,
        summary=summary,
        status=status_name,
        priority=priority_name,
        updated_at=updated,
        labels=labels,
    )


def _normalize_ticket_key(ticket_key: str) -> str:
    key = (ticket_key or "").strip().upper()
    if not _TICKET_KEY_RE.fullmatch(key):
        raise JiraInvalidTicketKeyError("ticket key must match format PROJECT-123")
    return key


def _jira_config(*, workspace_id: str | None = None) -> dict[str, str]:
    """Resolve Jira config from workspace connection or fall back to environment."""
    if workspace_id:
        try:
            from integrations.connection_service import resolve_connection_for_provider

            resolved = resolve_connection_for_provider(workspace_id, "jira")
            if resolved:
                credentials = resolved.get("credentials") or {}
                base_url = str(resolved.get("base_url") or "").strip().rstrip("/")
                email = str(credentials.get("email") or "").strip()
                api_token = str(credentials.get("api_token") or "").strip()
                if base_url and email and api_token:
                    parsed = parse.urlparse(base_url)
                    if parsed.scheme in {"http", "https"} and parsed.netloc:
                        if _EMAIL_RE.fullmatch(email):
                            return {
                                "base_url": base_url,
                                "email": email,
                                "api_token": api_token,
                            }
        except Exception:
            logger.debug("jira.config.db_resolution_failed workspace_id=%s", workspace_id, exc_info=True)
    return _jira_config_from_env()


def _jira_config_from_env() -> dict[str, str]:
    base_url = os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "").strip()
    api_token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if not base_url or not email or not api_token:
        raise JiraConfigError("JIRA config missing: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN")
    parsed = parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise JiraConfigError("JIRA_BASE_URL must be a valid http(s) URL")
    if not _EMAIL_RE.fullmatch(email):
        raise JiraConfigError("JIRA_EMAIL must be a valid email address")
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
    timeout_sec = _jira_timeout_sec()
    max_retries = _jira_max_retries()
    for attempt in range(max_retries + 1):
        try:
            with request.urlopen(req, timeout=timeout_sec) as resp:
                payload = resp.read().decode("utf-8")
                return json.loads(payload)
        except urlerror.HTTPError as exc:
            if exc.code in (401, 403):
                raise JiraAuthError("JIRA authentication failed") from exc
            if exc.code == 404:
                raise JiraNotFoundError(f"ticket not found: {ticket_key}") from exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                _sleep_before_retry(attempt)
                continue
            raise JiraExternalApiError(f"JIRA API request failed (status={exc.code})") from exc
        except urlerror.URLError as exc:
            if attempt < max_retries:
                _sleep_before_retry(attempt)
                continue
            raise JiraExternalApiError("JIRA API network failure") from exc
        except TimeoutError as exc:
            if attempt < max_retries:
                _sleep_before_retry(attempt)
                continue
            raise JiraExternalApiError("JIRA API request timed out") from exc
        except json.JSONDecodeError as exc:
            raise JiraExternalApiError("invalid JSON response from JIRA API") from exc
    raise JiraExternalApiError("JIRA API request failed after retries")


def _post_json_to_jira(cfg: dict[str, str], path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to JIRA REST API (e.g. search)."""
    url = f"{cfg['base_url']}{path}"
    data = json.dumps(body).encode("utf-8")
    auth_raw = f"{cfg['email']}:{cfg['api_token']}".encode("utf-8")
    auth_header = base64.b64encode(auth_raw).decode("ascii")

    req = request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_header}",
        },
        method="POST",
    )
    timeout_sec = _jira_timeout_sec()
    max_retries = _jira_max_retries()
    for attempt in range(max_retries + 1):
        try:
            with request.urlopen(req, timeout=timeout_sec) as resp:
                payload = resp.read().decode("utf-8")
                return json.loads(payload)
        except urlerror.HTTPError as exc:
            if exc.code in (401, 403):
                raise JiraAuthError("JIRA authentication failed") from exc
            if exc.code == 400:
                raise JiraInvalidSearchError("JIRA rejected the search (invalid JQL or query)") from exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                _sleep_before_retry(attempt)
                continue
            raise JiraExternalApiError(f"JIRA API request failed (status={exc.code})") from exc
        except urlerror.URLError as exc:
            if attempt < max_retries:
                _sleep_before_retry(attempt)
                continue
            raise JiraExternalApiError("JIRA API network failure") from exc
        except TimeoutError as exc:
            if attempt < max_retries:
                _sleep_before_retry(attempt)
                continue
            raise JiraExternalApiError("JIRA API request timed out") from exc
        except json.JSONDecodeError as exc:
            raise JiraExternalApiError("invalid JSON response from JIRA API") from exc
    raise JiraExternalApiError("JIRA API request failed after retries")


def _safe_read_error_body(exc: urlerror.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8")[:500]
    except Exception:
        return ""


def _jira_timeout_sec() -> int:
    raw = (os.environ.get("JIRA_TIMEOUT_SEC") or str(_DEFAULT_TIMEOUT_SEC)).strip()
    try:
        timeout = int(raw)
    except ValueError:
        raise JiraConfigError("JIRA_TIMEOUT_SEC must be an integer") from None
    if timeout <= 0 or timeout > 120:
        raise JiraConfigError("JIRA_TIMEOUT_SEC must be between 1 and 120 seconds")
    return timeout


def _jira_max_retries() -> int:
    raw = (os.environ.get("JIRA_MAX_RETRIES") or str(_DEFAULT_MAX_RETRIES)).strip()
    try:
        retries = int(raw)
    except ValueError:
        raise JiraConfigError("JIRA_MAX_RETRIES must be an integer") from None
    if retries < 0 or retries > 3:
        raise JiraConfigError("JIRA_MAX_RETRIES must be between 0 and 3")
    return retries


def _sleep_before_retry(attempt: int) -> None:
    # Minimal bounded backoff: 0.2s, 0.4s, 0.8s
    delay = min(0.2 * (2**attempt), 0.8)
    time.sleep(delay)


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
