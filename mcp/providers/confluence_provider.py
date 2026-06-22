"""Confluence MCP provider — normalized runbooks, known issues, and architecture docs."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from mcp.config import MCPFetchParams, confluence_mcp_enabled
from mcp.context.context_builder import merge_context
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.providers.base import BaseMCPProvider
from mcp.schemas.common import ProviderHealth, SourceMetadata
from mcp.schemas.confluence_models import ArchitectureDocument, KnownIssueDocument, RunbookDocument

logger = logging.getLogger(__name__)

_KNOWLEDGE_LABELS = ("runbook", "incident", "known-issue", "sop", "architecture")
_RUNBOOK_LABELS = frozenset({"runbook", "sop", "incident"})
_KNOWN_ISSUE_LABELS = frozenset({"known-issue", "known_issue", "knownissue"})
_ARCH_LABELS = frozenset({"architecture", "arch", "system-design"})
_TAG_RE = re.compile(r"<[^>]+>")


class ConfluenceProvider(BaseMCPProvider):
    source = "confluence"

    def is_enabled(self) -> bool:
        return confluence_mcp_enabled()

    def is_configured(self) -> bool:
        try:
            _confluence_cfg(allow_missing=False)
            return True
        except RuntimeError:
            return False

    def health_check(self) -> ProviderHealth:
        enabled = self.is_enabled()
        try:
            _confluence_cfg(allow_missing=False)
            configured = True
        except RuntimeError:
            configured = False

        if not enabled:
            return ProviderHealth(
                source="confluence",
                enabled=False,
                configured=configured,
                reachable=False,
                detail="disabled",
            )
        if not configured:
            return ProviderHealth(
                source="confluence",
                enabled=True,
                configured=False,
                reachable=False,
                detail="missing CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, or CONFLUENCE_API_TOKEN",
            )
        try:
            cfg = _confluence_cfg(allow_missing=False)
            _confluence_get(cfg, "/wiki/rest/api/user/current")
            return ProviderHealth(source="confluence", enabled=True, configured=True, reachable=True, detail="ok")
        except Exception as exc:
            return ProviderHealth(
                source="confluence",
                enabled=True,
                configured=True,
                reachable=False,
                detail=str(exc)[:200],
            )

    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        try:
            cfg = _confluence_cfg(allow_missing=False)
        except RuntimeError:
            return UnifiedInvestigationContext()

        search_terms = _build_search_terms(params)
        raw_pages = _search_pages(cfg, search_terms)

        runbooks: list[RunbookDocument] = []
        known_issues: list[KnownIssueDocument] = []
        architecture: list[ArchitectureDocument] = []
        seen: set[str] = set()

        for page in raw_pages[:40]:
            doc_id = str(page.get("id") or "")
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)

            detail = _fetch_page_detail(cfg, doc_id)
            merged = {**page, **detail} if detail else page
            labels = _extract_labels(merged)
            doc_type = _classify_document(merged, labels)

            if doc_type == "runbook":
                runbooks.append(_normalize_runbook(merged, labels, params.service_name))
            elif doc_type == "known_issue":
                known_issues.append(_normalize_known_issue(merged, labels, params.service_name))
            elif doc_type == "architecture":
                architecture.append(_normalize_architecture(merged, labels, params.service_name))

        meta = SourceMetadata(
            source="confluence",
            fetched_at=datetime.now(timezone.utc),
            ok=True,
            detail=(
                f"runbooks={len(runbooks)} known_issues={len(known_issues)} "
                f"architecture={len(architecture)}"
            ),
        )
        return merge_context(
            UnifiedInvestigationContext(),
            runbook_documents=runbooks,
            known_issue_documents=known_issues,
            architecture_documents=architecture,
            source_metadata=meta,
        )


def _confluence_cfg(*, allow_missing: bool) -> dict[str, str]:
    base_url = (os.environ.get("CONFLUENCE_BASE_URL") or "").strip().rstrip("/")
    email = (os.environ.get("CONFLUENCE_EMAIL") or "").strip()
    token = (os.environ.get("CONFLUENCE_API_TOKEN") or "").strip()
    space_key = (os.environ.get("CONFLUENCE_SPACE_KEY") or "").strip()
    if not base_url or not email or not token:
        if allow_missing:
            return {}
        raise RuntimeError("Confluence MCP config incomplete")
    return {
        "base_url": base_url,
        "email": email,
        "token": token,
        "space_key": space_key,
    }


def _confluence_headers(cfg: dict[str, str]) -> dict[str, str]:
    creds = base64.b64encode(f"{cfg['email']}:{cfg['token']}".encode()).decode()
    return {
        "Accept": "application/json",
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }


def _confluence_get(cfg: dict[str, str], path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    q = ""
    if query:
        q = "?" + parse.urlencode(query, doseq=True)
    url = f"{cfg['base_url']}{path}{q}"
    req = request.Request(url, headers=_confluence_headers(cfg), method="GET")
    timeout = int(os.environ.get("CONFLUENCE_TIMEOUT_SEC", "15"))
    with request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}


def _build_search_terms(params: MCPFetchParams) -> list[str]:
    terms: list[str] = []
    service = (params.service_name or "").strip()
    ticket = (params.ticket_key or "").strip()
    if service:
        terms.append(service)
    if ticket:
        terms.append(ticket)
    return terms


def _search_pages(cfg: dict[str, str], search_terms: list[str]) -> list[dict[str, Any]]:
    space_key = cfg.get("space_key", "")
    clauses: list[str] = ['type = "page"']
    if space_key:
        clauses.append(f'space = "{space_key}"')

    label_clause = " OR ".join(f'label = "{lbl}"' for lbl in _KNOWLEDGE_LABELS)
    text_clauses = [f'text ~ "{t}"' for t in search_terms if t]
    or_parts = [f"({label_clause})"]
    if text_clauses:
        or_parts.append(f"({' OR '.join(text_clauses)})")
    clauses.append(f"({' OR '.join(or_parts)})")
    cql = " AND ".join(clauses)

    try:
        payload = _confluence_get(
            cfg,
            "/wiki/rest/api/content/search",
            {"cql": cql, "limit": "40", "expand": "metadata.labels,space"},
        )
    except urlerror.HTTPError:
        return []
    results = payload.get("results")
    return results if isinstance(results, list) else []


def _fetch_page_detail(cfg: dict[str, str], page_id: str) -> dict[str, Any]:
    if not page_id:
        return {}
    try:
        return _confluence_get(
            cfg,
            f"/wiki/rest/api/content/{parse.quote(page_id)}",
            {"expand": "body.storage,version,metadata.labels,space"},
        )
    except urlerror.HTTPError:
        return {}


def _extract_labels(page: dict[str, Any]) -> list[str]:
    meta = page.get("metadata") or {}
    labels_block = meta.get("labels") or {}
    results = labels_block.get("results") or []
    out: list[str] = []
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip().lower()
                if name:
                    out.append(name)
    return out


def _classify_document(page: dict[str, Any], labels: list[str]) -> str | None:
    label_set = {lbl.lower() for lbl in labels}
    if label_set & _KNOWN_ISSUE_LABELS:
        return "known_issue"
    if label_set & _ARCH_LABELS:
        return "architecture"
    if label_set & _RUNBOOK_LABELS:
        return "runbook"

    title = str(page.get("title") or "").lower()
    excerpt = str(page.get("excerpt") or "").lower()
    combined = f"{title} {excerpt}"
    if "known issue" in combined or "known-issue" in combined:
        return "known_issue"
    if "architecture" in combined or "system design" in combined:
        return "architecture"
    if any(k in combined for k in ("runbook", "sop", "incident response", "rollback", "troubleshoot")):
        return "runbook"
    return None


def _page_url(cfg: dict[str, str], page: dict[str, Any]) -> str:
    links = page.get("_links") or {}
    webui = str(links.get("webui") or "")
    if webui.startswith("http"):
        return webui
    base = str(links.get("base") or cfg.get("base_url") or "").rstrip("/")
    if webui and base:
        return f"{base}{webui}"
    page_id = str(page.get("id") or "")
    space = page.get("space") or {}
    space_key = str(space.get("key") or cfg.get("space_key") or "")
    if page_id and space_key:
        return f"{cfg.get('base_url', '')}/wiki/spaces/{space_key}/pages/{page_id}"
    return ""


def _space_key(page: dict[str, Any], cfg: dict[str, str]) -> str:
    space = page.get("space") or {}
    return str(space.get("key") or cfg.get("space_key") or "")


def _updated_at(page: dict[str, Any]) -> str | None:
    version = page.get("version") or {}
    when = str(version.get("when") or "")
    return when or None


def _plain_text(page: dict[str, Any]) -> str:
    body = page.get("body") or {}
    storage = body.get("storage") or {}
    raw = str(storage.get("value") or page.get("excerpt") or "")
    text = _TAG_RE.sub(" ", raw)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _excerpt(text: str, limit: int = 400) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _infer_service_name(page: dict[str, Any], fallback: str) -> str:
    title = str(page.get("title") or "")
    text = _plain_text(page)
    for candidate in (title, text, fallback):
        match = re.search(r"\b([a-z][a-z0-9-]*-service)\b", candidate.lower())
        if match:
            return match.group(1)
    return fallback


def _extract_error_keywords(text: str) -> list[str]:
    lower = text.lower()
    bank = ("error", "exception", "timeout", "failed", "panic", "oom", "crash", "rollback", "outage")
    return [k for k in bank if k in lower]


def _extract_components(text: str) -> list[str]:
    components: list[str] = []
    for match in re.finditer(r"\b([A-Z][a-zA-Z0-9]+(?:Service|API|DB|Cache|Queue|Worker))\b", text):
        name = match.group(1)
        if name not in components:
            components.append(name)
    return components[:20]


def _normalize_runbook(page: dict[str, Any], labels: list[str], service_hint: str) -> RunbookDocument:
    cfg = {"base_url": (os.environ.get("CONFLUENCE_BASE_URL") or "").strip().rstrip("/")}
    text = _plain_text(page)
    service = _infer_service_name(page, (service_hint or "").strip())
    return RunbookDocument(
        document_id=str(page.get("id") or ""),
        title=str(page.get("title") or ""),
        space_key=_space_key(page, cfg),
        url=_page_url(cfg, page),
        service_name=service,
        summary=_excerpt(text, 200),
        content_excerpt=_excerpt(text, 400),
        labels=labels,
        updated_at=_updated_at(page),
    )


def _normalize_known_issue(page: dict[str, Any], labels: list[str], service_hint: str) -> KnownIssueDocument:
    cfg = {"base_url": (os.environ.get("CONFLUENCE_BASE_URL") or "").strip().rstrip("/")}
    text = _plain_text(page)
    service = _infer_service_name(page, (service_hint or "").strip())
    keywords = _extract_error_keywords(text)
    severity = ""
    for lbl in labels:
        if lbl in {"critical", "high", "medium", "low", "sev1", "sev2", "sev3"}:
            severity = lbl
            break
    workaround = ""
    workaround_match = re.search(r"workaround[:\s]+(.+?)(?:\n|$)", text, re.IGNORECASE)
    if workaround_match:
        workaround = _excerpt(workaround_match.group(1).strip(), 300)
    elif text:
        workaround = _excerpt(text, 300)

    return KnownIssueDocument(
        document_id=str(page.get("id") or ""),
        title=str(page.get("title") or ""),
        space_key=_space_key(page, cfg),
        url=_page_url(cfg, page),
        affected_service=service,
        error_keywords=keywords,
        workaround=workaround,
        severity=severity,
        updated_at=_updated_at(page),
    )


def _normalize_architecture(page: dict[str, Any], labels: list[str], service_hint: str) -> ArchitectureDocument:
    cfg = {"base_url": (os.environ.get("CONFLUENCE_BASE_URL") or "").strip().rstrip("/")}
    text = _plain_text(page)
    service = _infer_service_name(page, (service_hint or "").strip())
    return ArchitectureDocument(
        document_id=str(page.get("id") or ""),
        title=str(page.get("title") or ""),
        space_key=_space_key(page, cfg),
        url=_page_url(cfg, page),
        service_name=service,
        summary=_excerpt(text, 200),
        components=_extract_components(text),
        updated_at=_updated_at(page),
    )
