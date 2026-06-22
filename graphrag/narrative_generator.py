"""Deterministic investigation timeline and causal narrative from graph data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from mcp.context.investigation_context import UnifiedInvestigationContext


class TimelineEvent(BaseModel):
    """Chronological investigation event."""

    timestamp: Optional[str] = None
    event_type: str = ""
    title: str = ""
    detail: str = ""
    source: str = ""
    entity_ref: str = ""


class CausalChainLink(BaseModel):
    """Single step in the investigation causal chain."""

    step: int = 0
    entity_type: str = ""
    label: str = ""
    entity_ref: str = ""
    detail: str = ""


class InvestigationNarrative(BaseModel):
    """Structured investigation narrative derived from graph and MCP context."""

    timeline_events: list[TimelineEvent] = Field(default_factory=list)
    causal_chain: list[CausalChainLink] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    remediation_candidates: list[str] = Field(default_factory=list)
    confidence_summary: str = ""


def _parse_ts(value: str | None) -> datetime | None:
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


def _sort_key_ts(value: str | None) -> datetime:
    return _parse_ts(value) or datetime.min.replace(tzinfo=timezone.utc)


def _truncate(text: str, limit: int = 160) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 3].rstrip() + "..."


def _timeline_from_unified(context: UnifiedInvestigationContext) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []

    for pr in context.pull_requests:
        ts = pr.merged_at if pr.merged else pr.created_at
        events.append(
            TimelineEvent(
                timestamp=ts,
                event_type="pr_merged" if pr.merged else "pr_opened",
                title=f"PR #{pr.number} {'merged' if pr.merged else 'opened'}",
                detail=_truncate(pr.title),
                source="mcp",
                entity_ref=f"pr:{pr.number}",
            )
        )

    for mr in context.merge_requests:
        ts = mr.merged_at if mr.state == "merged" else mr.created_at
        events.append(
            TimelineEvent(
                timestamp=ts,
                event_type="merge_request_merged" if mr.state == "merged" else "merge_request_opened",
                title=f"MR !{mr.iid} {mr.state or 'updated'}",
                detail=_truncate(mr.title),
                source="mcp",
                entity_ref=f"mr:{mr.iid}",
            )
        )

    for commit in context.commits:
        sha = getattr(commit, "sha", None) or getattr(commit, "id", "")
        message = getattr(commit, "message", None) or getattr(commit, "title", "")
        events.append(
            TimelineEvent(
                timestamp=getattr(commit, "committed_at", None),
                event_type="commit",
                title=f"Commit {str(sha)[:8]}",
                detail=_truncate(str(message)),
                source="mcp",
                entity_ref=f"commit:{sha}",
            )
        )

    for build in context.build_events:
        events.append(
            TimelineEvent(
                timestamp=build.completed_at or build.started_at,
                event_type="build_completed",
                title=f"Build #{build.build_number} {build.status or 'completed'}".strip(),
                detail=_truncate(build.branch or build.build_url),
                source="mcp",
                entity_ref=f"build:{build.build_id or build.build_number}",
            )
        )

    for dep in context.deployment_events:
        env = getattr(dep, "environment", "") or ""
        events.append(
            TimelineEvent(
                timestamp=getattr(dep, "deployed_at", None),
                event_type="deployment_started",
                title=f"Deployment to {env or 'environment'}",
                detail=_truncate(getattr(dep, "deployment_url", None) or getattr(dep, "url", "") or dep.status),
                source="mcp",
                entity_ref=f"deployment:{getattr(dep, 'deployment_id', '') or env}",
            )
        )

    for metric in context.metric_events:
        if metric.severity not in {"high", "critical"} and metric.value <= 0:
            continue
        events.append(
            TimelineEvent(
                timestamp=metric.timestamp,
                event_type="metric_spike",
                title=f"Metric spike: {metric.metric_name or 'metric'}",
                detail=f"{metric.service} value={metric.value} {metric.unit}".strip(),
                source="mcp",
                entity_ref=f"metric:{metric.metric_name}:{metric.service}",
            )
        )

    for alert in context.alert_events:
        events.append(
            TimelineEvent(
                timestamp=alert.triggered_at,
                event_type="alert_fired",
                title=f"Alert: {alert.title or alert.alert_id}",
                detail=_truncate(alert.message or alert.severity),
                source="mcp",
                entity_ref=f"alert:{alert.alert_id or alert.title[:32]}",
            )
        )

    for pod in context.pod_events:
        if pod.restart_count <= 0 and pod.reason not in {"CrashLoopBackOff", "OOMKilled", "Error", "Failed"}:
            continue
        events.append(
            TimelineEvent(
                timestamp=pod.timestamp,
                event_type="pod_restarted" if pod.restart_count > 0 else "pod_failure",
                title=f"Pod {pod.pod_name} {pod.reason or pod.status}".strip(),
                detail=f"restarts={pod.restart_count} namespace={pod.namespace}",
                source="mcp",
                entity_ref=f"pod:{pod.namespace}/{pod.pod_name}",
            )
        )

    for incident in context.pagerduty_incidents:
        events.append(
            TimelineEvent(
                timestamp=incident.created_at,
                event_type="pagerduty_incident_created",
                title=f"PagerDuty incident: {incident.title or incident.incident_number}",
                detail=_truncate(incident.description or incident.urgency),
                source="mcp",
                entity_ref=f"incident:{incident.incident_id or incident.incident_number}",
            )
        )

    return events


def _timeline_from_graph(graph_context: dict[str, Any]) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []

    for commit in graph_context.get("related_commits") or []:
        if not isinstance(commit, dict):
            continue
        sha = str(commit.get("sha") or "")
        events.append(
            TimelineEvent(
                timestamp=commit.get("committed_at"),
                event_type="commit",
                title=f"Commit {sha[:8]}",
                detail=_truncate(str(commit.get("message") or "")),
                source="graph",
                entity_ref=f"commit:{sha}",
            )
        )

    for dep in graph_context.get("related_deployments") or []:
        if not isinstance(dep, dict):
            continue
        dep_id = str(dep.get("deployment_id") or "")
        events.append(
            TimelineEvent(
                timestamp=dep.get("deployed_at"),
                event_type="deployment_started",
                title=f"Deployment {dep.get('environment') or dep_id}",
                detail=_truncate(str(dep.get("status") or dep.get("commit_sha") or "")),
                source="graph",
                entity_ref=f"deployment:{dep_id}",
            )
        )

    for alert in graph_context.get("related_alerts") or []:
        if not isinstance(alert, dict):
            continue
        alert_id = str(alert.get("alert_id") or "")
        events.append(
            TimelineEvent(
                timestamp=alert.get("triggered_at"),
                event_type="alert_fired",
                title=f"Alert: {alert.get('title') or alert_id}",
                detail=_truncate(str(alert.get("message") or alert.get("severity") or "")),
                source="graph",
                entity_ref=f"alert:{alert_id}",
            )
        )

    for incident in graph_context.get("related_incidents") or []:
        if not isinstance(incident, dict):
            continue
        incident_id = str(incident.get("incident_id") or "")
        events.append(
            TimelineEvent(
                timestamp=incident.get("created_at"),
                event_type="pagerduty_incident_created",
                title=f"PagerDuty incident: {incident.get('title') or incident_id}",
                detail=_truncate(str(incident.get("urgency") or incident.get("status") or "")),
                source="graph",
                entity_ref=f"incident:{incident_id}",
            )
        )

    return events


def _dedupe_timeline(events: list[TimelineEvent]) -> list[TimelineEvent]:
    seen: set[str] = set()
    out: list[TimelineEvent] = []
    for event in events:
        key = f"{event.event_type}|{event.entity_ref}|{event.timestamp or ''}"
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return sorted(out, key=lambda e: (_sort_key_ts(e.timestamp), e.event_type, e.entity_ref))


def _pick_first(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _build_causal_chain(
    *,
    unified_context: UnifiedInvestigationContext | None,
    graph_context: dict[str, Any],
) -> list[CausalChainLink]:
    chain: list[CausalChainLink] = []
    step = 1

    commit_sha = ""
    if unified_context and unified_context.commits:
        first = unified_context.commits[0]
        commit_sha = getattr(first, "sha", None) or getattr(first, "id", "") or ""
        message = getattr(first, "message", None) or getattr(first, "title", "")
        chain.append(
            CausalChainLink(
                step=step,
                entity_type="commit",
                label=f"Commit {str(commit_sha)[:8]}",
                entity_ref=str(commit_sha),
                detail=_truncate(str(message)),
            )
        )
        step += 1
    elif graph_context.get("related_commits"):
        commit = graph_context["related_commits"][0]
        if isinstance(commit, dict):
            commit_sha = _pick_first(commit, "sha")
            chain.append(
                CausalChainLink(
                    step=step,
                    entity_type="commit",
                    label=f"Commit {commit_sha[:8]}",
                    entity_ref=commit_sha,
                    detail=_truncate(_pick_first(commit, "message")),
                )
            )
            step += 1

    build_label = ""
    if unified_context and unified_context.build_events:
        build = unified_context.build_events[0]
        build_label = f"Build #{build.build_number} {build.status}".strip()
        chain.append(
            CausalChainLink(
                step=step,
                entity_type="build",
                label=build_label,
                entity_ref=f"build:{build.build_id or build.build_number}",
                detail=_truncate(build.branch or build.build_url),
            )
        )
        step += 1

    deployment_id = ""
    deployment_env = ""
    if unified_context and unified_context.deployment_events:
        dep = unified_context.deployment_events[0]
        deployment_id = _pick_first(dep.model_dump(), "deployment_id") if hasattr(dep, "model_dump") else ""
        deployment_env = getattr(dep, "environment", "") or ""
        chain.append(
            CausalChainLink(
                step=step,
                entity_type="deployment",
                label=f"Deployment {deployment_env or deployment_id}",
                entity_ref=f"deployment:{deployment_id or deployment_env}",
                detail=_truncate(getattr(dep, "status", "") or getattr(dep, "commit_sha", "")),
            )
        )
        step += 1
    elif graph_context.get("related_deployments"):
        dep = graph_context["related_deployments"][0]
        if isinstance(dep, dict):
            deployment_id = _pick_first(dep, "deployment_id")
            deployment_env = _pick_first(dep, "environment")
            chain.append(
                CausalChainLink(
                    step=step,
                    entity_type="deployment",
                    label=f"Deployment {deployment_env or deployment_id}",
                    entity_ref=f"deployment:{deployment_id}",
                    detail=_truncate(_pick_first(dep, "status", "commit_sha")),
                )
            )
            step += 1

    pod_reason = ""
    if unified_context and unified_context.pod_events:
        pod = next(
            (p for p in unified_context.pod_events if p.reason or p.restart_count > 0),
            unified_context.pod_events[0],
        )
        pod_reason = pod.reason or ("restart" if pod.restart_count > 0 else pod.status)
        chain.append(
            CausalChainLink(
                step=step,
                entity_type="pod",
                label=pod.reason or f"Pod {pod.pod_name}",
                entity_ref=f"pod:{pod.namespace}/{pod.pod_name}",
                detail=f"status={pod.status} restarts={pod.restart_count}",
            )
        )
        step += 1

    metric_name = ""
    if unified_context and unified_context.metric_events:
        metric = unified_context.metric_events[0]
        metric_name = metric.metric_name or "metric"
        chain.append(
            CausalChainLink(
                step=step,
                entity_type="metric",
                label=f"{metric_name} spike",
                entity_ref=f"metric:{metric_name}:{metric.service}",
                detail=f"severity={metric.severity} value={metric.value}",
            )
        )
        step += 1

    alert_id = ""
    if unified_context and unified_context.alert_events:
        alert = unified_context.alert_events[0]
        alert_id = alert.alert_id or alert.title[:32]
        chain.append(
            CausalChainLink(
                step=step,
                entity_type="alert",
                label=alert.title or "Alert fired",
                entity_ref=f"alert:{alert_id}",
                detail=_truncate(alert.message or alert.severity),
            )
        )
        step += 1
    elif graph_context.get("related_alerts"):
        alert = graph_context["related_alerts"][0]
        if isinstance(alert, dict):
            alert_id = _pick_first(alert, "alert_id", "title")
            chain.append(
                CausalChainLink(
                    step=step,
                    entity_type="alert",
                    label=_pick_first(alert, "title") or "Alert fired",
                    entity_ref=f"alert:{alert_id}",
                    detail=_truncate(_pick_first(alert, "message", "severity")),
                )
            )
            step += 1

    if unified_context and unified_context.pagerduty_incidents:
        incident = unified_context.pagerduty_incidents[0]
        chain.append(
            CausalChainLink(
                step=step,
                entity_type="incident",
                label=incident.title or f"Incident #{incident.incident_number}",
                entity_ref=f"incident:{incident.incident_id or incident.incident_number}",
                detail=_truncate(incident.description or incident.urgency),
            )
        )
    elif graph_context.get("related_incidents"):
        incident = graph_context["related_incidents"][0]
        if isinstance(incident, dict):
            incident_id = _pick_first(incident, "incident_id")
            chain.append(
                CausalChainLink(
                    step=step,
                    entity_type="incident",
                    label=_pick_first(incident, "title") or "PagerDuty incident",
                    entity_ref=f"incident:{incident_id}",
                    detail=_truncate(_pick_first(incident, "urgency", "status")),
                )
            )

    return chain


def _build_supporting_evidence(graph_context: dict[str, Any]) -> list[str]:
    evidence: list[str] = []

    for dep in graph_context.get("related_deployments") or []:
        if not isinstance(dep, dict):
            continue
        evidence.append(
            "Deployment {env} ({status}) commit {sha}".format(
                env=_pick_first(dep, "environment") or "unknown",
                status=_pick_first(dep, "status") or "unknown",
                sha=_pick_first(dep, "commit_sha")[:8],
            ).strip()
        )

    for alert in graph_context.get("related_alerts") or []:
        if not isinstance(alert, dict):
            continue
        evidence.append(
            f"Alert '{_pick_first(alert, 'title')}' ({_pick_first(alert, 'severity')}) on {_pick_first(alert, 'service')}"
        )

    for incident in graph_context.get("related_incidents") or []:
        if not isinstance(incident, dict):
            continue
        evidence.append(
            f"PagerDuty incident '{_pick_first(incident, 'title')}' status={_pick_first(incident, 'status')}"
        )

    for runbook in graph_context.get("runbooks") or []:
        if not isinstance(runbook, dict):
            continue
        evidence.append(f"Runbook available: {_pick_first(runbook, 'title')}")

    for known in graph_context.get("known_issues") or []:
        if not isinstance(known, dict):
            continue
        evidence.append(
            f"Known issue '{_pick_first(known, 'title')}' affects {_pick_first(known, 'affected_service')}"
        )

    return evidence[:12]


def _build_remediation_candidates(
    *,
    unified_context: UnifiedInvestigationContext | None,
    graph_context: dict[str, Any],
) -> list[str]:
    candidates: list[str] = []

    for runbook in graph_context.get("runbooks") or []:
        if not isinstance(runbook, dict):
            continue
        summary = _pick_first(runbook, "summary", "title")
        if summary:
            candidates.append(f"Follow runbook: {summary}")

    for known in graph_context.get("known_issues") or []:
        if not isinstance(known, dict):
            continue
        workaround = _pick_first(known, "workaround")
        if workaround:
            candidates.append(f"Known-issue workaround: {_truncate(workaround, 200)}")

    if unified_context:
        for doc in unified_context.runbook_documents:
            if doc.summary:
                candidates.append(f"Runbook guidance: {_truncate(doc.summary, 200)}")
        for doc in unified_context.known_issue_documents:
            if doc.workaround:
                candidates.append(f"Known issue workaround: {_truncate(doc.workaround, 200)}")

    seen: set[str] = set()
    out: list[str] = []
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out[:8]


def _build_confidence_summary(rca_result: dict[str, Any]) -> str:
    candidates = rca_result.get("candidates")
    if not isinstance(candidates, list):
        candidates = rca_result.get("ranked_hypotheses") or []
    if not isinstance(candidates, list) or not candidates:
        return "Deterministic RCA ranking unavailable; narrative confidence is limited."

    top = candidates[0] if isinstance(candidates[0], dict) else {}
    path = _pick_first(top, "path", "file_id") or "top candidate"

    assessment = top.get("confidence_assessment")
    if isinstance(assessment, dict) and assessment.get("confidence") is not None:
        try:
            evidence_conf = float(assessment.get("confidence") or 0.0)
        except (TypeError, ValueError):
            evidence_conf = 0.0
        level = str(assessment.get("confidence_level") or "low")
        supporting = assessment.get("supporting_factors") or []
        contradicting = assessment.get("contradicting_factors") or []
        summary = (
            f"Evidence confidence for {path} is {evidence_conf:.2f} ({level}). "
            f"Ranking score {top.get('confidence', 'n/a')} remains authoritative for candidate order."
        )
        if supporting:
            summary += f" Supporting: {'; '.join(str(s) for s in supporting[:3])}."
        if contradicting:
            summary += f" Caveats: {'; '.join(str(c) for c in contradicting[:3])}."
        return summary

    confidence = top.get("confidence")
    try:
        conf_text = f"{float(confidence):.2f}"
    except (TypeError, ValueError):
        conf_text = "n/a"
    return (
        f"Deterministic RCA top candidate is {path} with confidence {conf_text}. "
        "Narrative links are assistive and do not override ranking."
    )


def _build_investigation_summary(narrative: InvestigationNarrative) -> str:
    if narrative.causal_chain:
        steps = " → ".join(link.label for link in narrative.causal_chain[:8])
        prefix = f"Causal chain: {steps}."
    else:
        prefix = "Causal chain could not be fully reconstructed from available graph context."

    if narrative.supporting_evidence:
        evidence = narrative.supporting_evidence[0]
        return f"{prefix} Key evidence: {evidence}"
    return prefix


def generate_investigation_narrative(
    rca_result: dict[str, Any],
    *,
    unified_context: UnifiedInvestigationContext | None = None,
    graph_context: dict[str, Any] | None = None,
) -> InvestigationNarrative:
    """
    Build a structured investigation narrative from RCA output and graph retrieval context.

    Deterministic only — does not call an LLM and does not modify RCA ranking.
    """
    graph_ctx = graph_context if isinstance(graph_context, dict) else {}

    timeline: list[TimelineEvent] = []
    if unified_context is not None:
        timeline.extend(_timeline_from_unified(unified_context))
    timeline.extend(_timeline_from_graph(graph_ctx))
    timeline_events = _dedupe_timeline(timeline)

    causal_chain = _build_causal_chain(unified_context=unified_context, graph_context=graph_ctx)
    supporting_evidence = _build_supporting_evidence(graph_ctx)
    remediation_candidates = _build_remediation_candidates(
        unified_context=unified_context,
        graph_context=graph_ctx,
    )
    confidence_summary = _build_confidence_summary(rca_result)

    return InvestigationNarrative(
        timeline_events=timeline_events,
        causal_chain=causal_chain,
        supporting_evidence=supporting_evidence,
        remediation_candidates=remediation_candidates,
        confidence_summary=confidence_summary,
    )


def attach_narrative_to_output(
    output: dict[str, Any],
    narrative: InvestigationNarrative,
) -> dict[str, Any]:
    """Attach narrative fields to an explanation payload without mutating RCA ranking."""
    merged = dict(output)
    merged["timeline"] = [event.model_dump() for event in narrative.timeline_events]
    merged["causal_chain"] = [link.model_dump() for link in narrative.causal_chain]
    merged["investigation_summary"] = _build_investigation_summary(narrative)
    merged["investigation_narrative"] = narrative.model_dump()
    return merged
