"""PagerDuty MCP provider — normalized incidents, escalations, and timeline events."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from mcp.config import MCPFetchParams, pagerduty_mcp_enabled
from mcp.context.context_builder import merge_context
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.providers.base import BaseMCPProvider
from mcp.schemas.common import ProviderHealth, SourceMetadata
from mcp.schemas.pagerduty_models import (
    PagerDutyEscalationEvent,
    PagerDutyIncidentEvent,
    PagerDutyTimelineEvent,
)

logger = logging.getLogger(__name__)

_API_BASE = "https://api.pagerduty.com"


class PagerDutyProvider(BaseMCPProvider):
    source = "pagerduty"

    def is_enabled(self) -> bool:
        return pagerduty_mcp_enabled()

    def is_configured(self) -> bool:
        try:
            _pagerduty_cfg(allow_missing=False)
            return True
        except RuntimeError:
            return False

    def health_check(self) -> ProviderHealth:
        enabled = self.is_enabled()
        try:
            _pagerduty_cfg(allow_missing=False)
            configured = True
        except RuntimeError:
            configured = False

        if not enabled:
            return ProviderHealth(
                source="pagerduty",
                enabled=False,
                configured=configured,
                reachable=False,
                detail="disabled",
            )
        if not configured:
            return ProviderHealth(
                source="pagerduty",
                enabled=True,
                configured=False,
                reachable=False,
                detail="missing PAGERDUTY_API_TOKEN",
            )
        try:
            cfg = _pagerduty_cfg(allow_missing=False)
            _pagerduty_get(cfg, "/abilities")
            return ProviderHealth(source="pagerduty", enabled=True, configured=True, reachable=True, detail="ok")
        except Exception as exc:
            return ProviderHealth(
                source="pagerduty",
                enabled=True,
                configured=True,
                reachable=False,
                detail=str(exc)[:200],
            )

    def fetch(self, params: MCPFetchParams) -> UnifiedInvestigationContext:
        try:
            cfg = _pagerduty_cfg(allow_missing=False)
        except RuntimeError:
            return UnifiedInvestigationContext()

        since, until = _resolve_window(params)
        incidents_raw = _fetch_incidents(cfg, since=since, until=until, service_id=cfg.get("service_id", ""))

        incidents: list[PagerDutyIncidentEvent] = []
        escalations: list[PagerDutyEscalationEvent] = []
        timeline: list[PagerDutyTimelineEvent] = []

        for item in incidents_raw[:30]:
            incident = _normalize_incident(item)
            incidents.append(incident)
            escalations.extend(_normalize_escalations(item))
            timeline.extend(_fetch_timeline(cfg, str(item.get("id") or "")))

        meta = SourceMetadata(
            source="pagerduty",
            fetched_at=datetime.now(timezone.utc),
            ok=True,
            detail=f"incidents={len(incidents)} escalations={len(escalations)} timeline={len(timeline)}",
        )
        return merge_context(
            UnifiedInvestigationContext(),
            pagerduty_incidents=incidents,
            pagerduty_escalations=escalations,
            pagerduty_timeline_events=timeline,
            source_metadata=meta,
        )


def _pagerduty_cfg(*, allow_missing: bool) -> dict[str, str]:
    token = (os.environ.get("PAGERDUTY_API_TOKEN") or "").strip()
    service_id = (os.environ.get("PAGERDUTY_SERVICE_ID") or "").strip()
    if not token:
        if allow_missing:
            return {}
        raise RuntimeError("PagerDuty MCP config incomplete")
    return {
        "token": token,
        "service_id": service_id,
        "api_base": (os.environ.get("PAGERDUTY_API_BASE") or _API_BASE).strip().rstrip("/"),
    }


def _pagerduty_headers(cfg: dict[str, str]) -> dict[str, str]:
    return {
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Authorization": f"Token token={cfg['token']}",
        "Content-Type": "application/json",
    }


def _pagerduty_get(cfg: dict[str, str], path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    q = ""
    if query:
        q = "?" + parse.urlencode(query, doseq=True)
    url = f"{cfg['api_base']}{path}{q}"
    req = request.Request(url, headers=_pagerduty_headers(cfg), method="GET")
    timeout = int(os.environ.get("PAGERDUTY_TIMEOUT_SEC", "15"))
    with request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}


def _resolve_window(params: MCPFetchParams) -> tuple[str, str]:
    end = _iso_or_now(params.end_time)
    start = params.start_time
    if not start:
        lookback = int(os.environ.get("PAGERDUTY_LOOKBACK_MINUTES", "60"))
        end_dt = _parse_iso(end) or datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(minutes=lookback)
        start = start_dt.isoformat().replace("+00:00", "Z")
    return start, end


def _iso_or_now(value: str | None) -> str:
    if (value or "").strip():
        return value.strip()
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _fetch_incidents(
    cfg: dict[str, str],
    *,
    since: str,
    until: str,
    service_id: str,
) -> list[dict[str, Any]]:
    query: dict[str, str | list[str]] = {
        "since": since,
        "until": until,
        "limit": "50",
        "sort_by": "created_at:desc",
    }
    if service_id:
        query["service_ids[]"] = service_id
    try:
        payload = _pagerduty_get(cfg, "/incidents", query)
    except urlerror.HTTPError:
        return []
    incidents = payload.get("incidents")
    return incidents if isinstance(incidents, list) else []


def _normalize_incident(item: dict[str, Any]) -> PagerDutyIncidentEvent:
    service = item.get("service") or {}
    service_name = str(service.get("summary") or service.get("name") or "")
    acks = item.get("acknowledgements") or []
    acknowledged_at = None
    if isinstance(acks, list) and acks:
        first = acks[0]
        if isinstance(first, dict):
            acknowledged_at = str(first.get("at") or "") or None
    resolved_at = None
    if str(item.get("status") or "") == "resolved":
        resolved_at = str(item.get("last_status_change_at") or item.get("resolved_at") or "") or None
    return PagerDutyIncidentEvent(
        incident_id=str(item.get("id") or ""),
        incident_number=int(item.get("incident_number") or 0),
        title=str(item.get("title") or ""),
        description=str(item.get("description") or ""),
        service_name=service_name,
        urgency=str(item.get("urgency") or ""),
        status=str(item.get("status") or ""),
        created_at=str(item.get("created_at") or "") or None,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
        html_url=str(item.get("html_url") or ""),
    )


def _normalize_escalations(item: dict[str, Any]) -> list[PagerDutyEscalationEvent]:
    incident_id = str(item.get("id") or "")
    policy = item.get("escalation_policy") or {}
    policy_id = str(policy.get("id") or "")
    policy_name = str(policy.get("summary") or policy.get("name") or "")
    out: list[PagerDutyEscalationEvent] = []

    assignments = item.get("assignments") or []
    if not isinstance(assignments, list):
        return out
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        assignee = assignment.get("assignee") or {}
        out.append(
            PagerDutyEscalationEvent(
                escalation_policy_id=policy_id,
                escalation_policy_name=policy_name,
                incident_id=incident_id,
                responder_name=str(assignee.get("summary") or assignee.get("name") or ""),
                responder_email=str(assignee.get("email") or ""),
                assigned_at=str(assignment.get("at") or item.get("created_at") or "") or None,
                acknowledged_at=None,
            )
        )
    return out


def _fetch_timeline(cfg: dict[str, str], incident_id: str) -> list[PagerDutyTimelineEvent]:
    if not incident_id:
        return []
    try:
        payload = _pagerduty_get(cfg, f"/incidents/{parse.quote(incident_id)}/log_entries", {"limit": "30"})
    except urlerror.HTTPError:
        return []
    entries = payload.get("log_entries")
    if not isinstance(entries, list):
        return []
    out: list[PagerDutyTimelineEvent] = []
    for entry in entries[:30]:
        if not isinstance(entry, dict):
            continue
        agent = entry.get("agent") or {}
        out.append(
            PagerDutyTimelineEvent(
                event_id=str(entry.get("id") or ""),
                incident_id=incident_id,
                event_type=str(entry.get("type") or entry.get("channel", {}).get("type") or ""),
                summary=str(entry.get("summary") or ""),
                created_at=str(entry.get("created_at") or "") or None,
                actor_name=str(agent.get("summary") or agent.get("name") or ""),
            )
        )
    return out
