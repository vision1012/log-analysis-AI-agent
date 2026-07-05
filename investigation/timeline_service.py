"""
Unified chronological investigation timeline.

Aggregates MCP investigation graph nodes and feedback into timeline events.
Does not modify RCA ranking or GraphRAG behavior.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Optional

from feedback.feedback_learning_service import get_feedback_for_investigation
from graph.graph_visualization_service import investigation_exists
from graph.neo4j_client import Neo4jClient
from investigation.timeline_models import InvestigationTimelineEvent

TRAVERSAL_MAX_HOPS = 10

SOURCE_JIRA = "Jira"
SOURCE_GITHUB = "GitHub"
SOURCE_GITLAB = "GitLab"
SOURCE_JENKINS = "Jenkins"
SOURCE_DATADOG = "Datadog"
SOURCE_KUBERNETES = "Kubernetes"
SOURCE_PAGERDUTY = "PagerDuty"
SOURCE_CONFLUENCE = "Confluence"
SOURCE_RCA = "RCA"
SOURCE_FEEDBACK = "Feedback"


def _stable_event_id(*parts: str) -> str:
    raw = "|".join((p or "").strip() for p in parts if (p or "").strip())
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"evt:{digest}"


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _parse_timestamp(value: str | None) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _timestamp_sort_key(timestamp: str) -> tuple[int, str]:
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return (1, timestamp or "")
    return (0, parsed.isoformat())


def _get_investigation_store():
    from artifacts.investigation_store import LocalFileInvestigationStore

    base = os.environ.get("JIRA_INVESTIGATION_STORE_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        "jira_rca_investigations",
    )
    return LocalFileInvestigationStore(base)


def _event(
    *,
    event_type: str,
    source: str,
    title: str,
    timestamp: str = "",
    description: str = "",
    severity: str = "",
    metadata: dict[str, Any] | None = None,
    event_id: str = "",
) -> InvestigationTimelineEvent | None:
    if not title and not description:
        return None
    ts = _text(timestamp)
    eid = event_id or _stable_event_id(event_type, source, title, ts)
    return InvestigationTimelineEvent(
        event_id=eid,
        timestamp=ts,
        event_type=event_type,
        source=source,
        title=title,
        description=description,
        severity=_text(severity),
        metadata=dict(metadata or {}),
    )


def _feedback_fields(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    return {
        "feedback_id": getattr(record, "feedback_id", ""),
        "feedback_type": getattr(record, "feedback_type", ""),
        "candidate_id": getattr(record, "candidate_id", ""),
        "comments": getattr(record, "comments", ""),
        "user_id": getattr(record, "user_id", ""),
        "created_at": getattr(record, "created_at", ""),
        "override_candidate_id": getattr(record, "override_candidate_id", ""),
    }


def _fetch_investigation_context(client: Neo4jClient, investigation_id: str) -> dict[str, Any]:
    rows = client.execute_read(
        """
        MATCH (i:Investigation {id: $investigation_id})
        OPTIONAL MATCH (i)-[:HAS_JIRA_TICKET]->(t:JiraTicket)
        RETURN i.created_at AS investigation_created_at, properties(t) AS ticket_props
        """,
        {"investigation_id": investigation_id},
    )
    return rows[0] if rows else {}


def _fetch_graph_nodes(client: Neo4jClient, investigation_id: str) -> list[dict[str, Any]]:
    return client.execute_read(
        f"""
        MATCH (i:Investigation {{id: $investigation_id}})
        OPTIONAL MATCH (i)-[*1..{TRAVERSAL_MAX_HOPS}]-(n)
        WHERE n IS NOT NULL
          AND NOT n:Investigation
          AND NOT n:Service
          AND NOT n:User
          AND NOT n:RCACandidate
        RETURN DISTINCT labels(n) AS labels, properties(n) AS props
        UNION
        MATCH (i:Investigation {{id: $investigation_id}})-[:HAS_FEEDBACK]->(f:Feedback)
        RETURN labels(f) AS labels, properties(f) AS props
        """,
        {"investigation_id": investigation_id},
    )


def _primary_label(labels: list[str]) -> str:
    for label in labels or []:
        if label not in {"Investigation"}:
            return label
    return labels[0] if labels else "Unknown"


def _gitlab_source(props: dict[str, Any]) -> bool:
    repo_ref = _text(props.get("repo_ref")).lower()
    deployment_url = _text(props.get("deployment_url")).lower()
    build_url = _text(props.get("build_url")).lower()
    return "gitlab" in repo_ref or "gitlab" in deployment_url or "gitlab" in build_url


def _events_from_jira_ticket(
    ticket_props: dict[str, Any] | None,
    *,
    investigation_created_at: str,
) -> list[InvestigationTimelineEvent]:
    if not ticket_props:
        return []
    title = _text(ticket_props.get("summary")) or _text(ticket_props.get("issue_key"), "Jira ticket")
    description = _text(ticket_props.get("description"))
    status = _text(ticket_props.get("status"))
    if status and not description:
        description = f"Status: {status}"
    event = _event(
        event_type="JIRA_CREATED",
        source=SOURCE_JIRA,
        title=title,
        timestamp=investigation_created_at,
        description=description,
        severity=_text(ticket_props.get("priority")),
        metadata={
            "issue_key": _text(ticket_props.get("issue_key")),
            "url": _text(ticket_props.get("url")),
            "status": status,
        },
    )
    return [event] if event else []


def _events_from_pull_request(props: dict[str, Any], *, source: str) -> list[InvestigationTimelineEvent]:
    title = _text(props.get("title")) or f"Pull request #{props.get('number', '')}"
    merged = bool(props.get("merged")) or _text(props.get("state")).lower() == "merged"
    if not merged:
        return []
    event = _event(
        event_type="PR_MERGED",
        source=source,
        title=title,
        timestamp=_text(props.get("merged_at")) or _text(props.get("created_at")),
        description=f"Merged pull request by {_text(props.get('author'))}".strip(),
        metadata={
            "number": props.get("number"),
            "url": _text(props.get("url")),
            "state": _text(props.get("state")),
        },
    )
    return [event] if event else []


def _events_from_commit(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    source = SOURCE_GITLAB if _gitlab_source(props) else SOURCE_GITHUB
    sha = _text(props.get("sha"))
    message = _text(props.get("message")) or "Commit pushed"
    event = _event(
        event_type="COMMIT_PUSHED",
        source=source,
        title=message.splitlines()[0] if message else "Commit pushed",
        timestamp=_text(props.get("committed_at")),
        description=message,
        metadata={
            "sha": sha,
            "author": _text(props.get("author")),
            "repo_ref": _text(props.get("repo_ref")),
        },
    )
    return [event] if event else []


def _events_from_build(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    events: list[InvestigationTimelineEvent] = []
    title = f"Build #{props.get('build_number', '')}".strip() or "Build"
    started = _event(
        event_type="BUILD_STARTED",
        source=SOURCE_JENKINS,
        title=f"{title} started",
        timestamp=_text(props.get("started_at")),
        description=_text(props.get("branch")),
        metadata={
            "build_id": _text(props.get("id")),
            "status": _text(props.get("status")),
            "build_url": _text(props.get("build_url")),
            "commit_sha": _text(props.get("commit_sha")),
        },
    )
    if started:
        events.append(started)
    completed_at = _text(props.get("completed_at"))
    if completed_at:
        completed = _event(
            event_type="BUILD_COMPLETED",
            source=SOURCE_JENKINS,
            title=f"{title} completed",
            timestamp=completed_at,
            description=_text(props.get("status")),
            metadata={
                "build_id": _text(props.get("id")),
                "status": _text(props.get("status")),
                "build_url": _text(props.get("build_url")),
            },
        )
        if completed:
            events.append(completed)
    return events


def _events_from_deployment(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    source = SOURCE_GITLAB if _gitlab_source(props) else SOURCE_JENKINS
    environment = _text(props.get("environment"), "environment")
    deployed_at = _text(props.get("deployed_at"))
    status = _text(props.get("status")).lower()
    events: list[InvestigationTimelineEvent] = []
    started = _event(
        event_type="DEPLOYMENT_STARTED",
        source=source,
        title=f"Deployment to {environment} started",
        timestamp=deployed_at,
        description=_text(props.get("deployment_url")),
        metadata={
            "deployment_id": _text(props.get("id")),
            "commit_sha": _text(props.get("commit_sha")),
            "status": status,
        },
    )
    if started:
        events.append(started)
    if deployed_at and status in {"success", "succeeded", "completed", "deployed", "active"}:
        completed = _event(
            event_type="DEPLOYMENT_COMPLETED",
            source=source,
            title=f"Deployment to {environment} completed",
            timestamp=deployed_at,
            description=_text(props.get("deployment_url")),
            metadata={
                "deployment_id": _text(props.get("id")),
                "commit_sha": _text(props.get("commit_sha")),
                "status": status,
            },
        )
        if completed:
            events.append(completed)
    return events


def _events_from_metric(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    metric_name = _text(props.get("metric_name"), "metric")
    value = props.get("value")
    unit = _text(props.get("unit"))
    description = f"{metric_name}={value} {unit}".strip()
    event = _event(
        event_type="METRIC_SPIKE",
        source=SOURCE_DATADOG,
        title=f"Metric spike: {metric_name}",
        timestamp=_text(props.get("timestamp")),
        description=description,
        severity=_text(props.get("severity")),
        metadata={
            "metric_id": _text(props.get("id")),
            "service": _text(props.get("service")),
            "value": value,
            "unit": unit,
        },
    )
    return [event] if event else []


def _events_from_alert(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    title = _text(props.get("title"), "Alert triggered")
    event = _event(
        event_type="ALERT_TRIGGERED",
        source=SOURCE_DATADOG,
        title=title,
        timestamp=_text(props.get("triggered_at")),
        description=_text(props.get("message")),
        severity=_text(props.get("severity")),
        metadata={
            "alert_id": _text(props.get("id")),
            "service": _text(props.get("service")),
            "status": _text(props.get("status")),
        },
    )
    return [event] if event else []


def _events_from_trace(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    error_count = int(props.get("error_count") or 0)
    if error_count <= 0:
        return []
    endpoint = _text(props.get("endpoint"), "endpoint")
    event = _event(
        event_type="TRACE_FAILURE",
        source=SOURCE_DATADOG,
        title=f"Trace failures on {endpoint}",
        timestamp=_text(props.get("timestamp")),
        description=f"{error_count} trace error(s) detected",
        severity="high" if error_count >= 5 else "medium",
        metadata={
            "trace_id": _text(props.get("id")),
            "service": _text(props.get("service")),
            "endpoint": endpoint,
            "error_count": error_count,
            "latency_ms": props.get("latency_ms"),
        },
    )
    return [event] if event else []


def _events_from_pod(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    restart_count = int(props.get("restart_count") or 0)
    reason = _text(props.get("reason")).lower()
    if restart_count <= 0 and "restart" not in reason:
        return []
    pod_name = _text(props.get("pod_name"), "pod")
    event = _event(
        event_type="POD_RESTART",
        source=SOURCE_KUBERNETES,
        title=f"Pod restart: {pod_name}",
        timestamp=_text(props.get("timestamp")),
        description=reason or f"Restart count: {restart_count}",
        severity="medium",
        metadata={
            "pod_id": _text(props.get("id")),
            "namespace": _text(props.get("namespace")),
            "node_name": _text(props.get("node_name")),
            "restart_count": restart_count,
        },
    )
    return [event] if event else []


def _events_from_container(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    reason = _text(props.get("reason")).lower()
    if "oom" not in reason and "oomkilled" not in reason:
        return []
    container_name = _text(props.get("container_name"), "container")
    event = _event(
        event_type="OOM_KILLED",
        source=SOURCE_KUBERNETES,
        title=f"OOM killed: {container_name}",
        timestamp=_text(props.get("timestamp")),
        description=reason or "Container terminated due to OOM",
        severity="high",
        metadata={
            "container_id": _text(props.get("id")),
            "pod_name": _text(props.get("pod_name")),
            "image": _text(props.get("image")),
            "status": _text(props.get("status")),
        },
    )
    return [event] if event else []


def _events_from_incident(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    events: list[InvestigationTimelineEvent] = []
    title = _text(props.get("title"), "PagerDuty incident")
    created_at = _text(props.get("created_at"))
    status = _text(props.get("status")).lower()
    opened = _event(
        event_type="INCIDENT_OPENED",
        source=SOURCE_PAGERDUTY,
        title=title,
        timestamp=created_at,
        description=_text(props.get("description")),
        severity=_text(props.get("urgency")),
        metadata={
            "incident_id": _text(props.get("id")),
            "incident_number": props.get("incident_number"),
            "service_name": _text(props.get("service_name")),
            "html_url": _text(props.get("html_url")),
        },
    )
    if opened:
        events.append(opened)
    if status in {"acknowledged", "triggered", "resolved"}:
        ack = _event(
            event_type="INCIDENT_ACKNOWLEDGED",
            source=SOURCE_PAGERDUTY,
            title=f"{title} acknowledged",
            timestamp=_text(props.get("acknowledged_at")) or created_at,
            description=f"Incident status: {status}",
            severity=_text(props.get("urgency")),
            metadata={
                "incident_id": _text(props.get("id")),
                "status": status,
            },
        )
        if ack:
            events.append(ack)
    return events


def _events_from_runbook(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    title = _text(props.get("title"), "Runbook matched")
    event = _event(
        event_type="RUNBOOK_MATCHED",
        source=SOURCE_CONFLUENCE,
        title=title,
        timestamp=_text(props.get("updated_at")),
        description=_text(props.get("summary")),
        metadata={
            "runbook_id": _text(props.get("id")),
            "service_name": _text(props.get("service_name")),
            "url": _text(props.get("url")),
            "space_key": _text(props.get("space_key")),
        },
    )
    return [event] if event else []


def _events_from_architecture_document(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    title = _text(props.get("title"), "Architecture reference")
    subsystem = _text(props.get("subsystem"))
    if not subsystem:
        components = _text(props.get("components"))
        if components:
            subsystem = components.split(",")[0].strip()
    event = _event(
        event_type="ARCHITECTURE_REFERENCE",
        source=SOURCE_CONFLUENCE,
        title=title,
        timestamp=_text(props.get("updated_at")),
        description=_text(props.get("summary")),
        metadata={
            "document_id": _text(props.get("document_id") or props.get("id")),
            "summary": _text(props.get("summary")),
            "document_url": _text(props.get("url")),
            "service": _text(props.get("service_name")),
            "subsystem": subsystem,
            "space_key": _text(props.get("space_key")),
        },
    )
    return [event] if event else []


def _events_from_known_issue(props: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    title = _text(props.get("title"), "Known issue matched")
    description = _text(props.get("workaround"))
    if not description:
        affected = _text(props.get("affected_service"))
        description = f"Affects {affected}" if affected else "Known issue linked to investigation"
    event = _event(
        event_type="KNOWN_ISSUE_MATCHED",
        source=SOURCE_CONFLUENCE,
        title=title,
        timestamp=_text(props.get("updated_at")),
        description=description,
        severity=_text(props.get("severity")),
        metadata={
            "known_issue_id": _text(props.get("id")),
            "affected_service": _text(props.get("affected_service")),
            "url": _text(props.get("url")),
            "space_key": _text(props.get("space_key")),
        },
    )
    return [event] if event else []


def _events_from_feedback_record(record: Any) -> list[InvestigationTimelineEvent]:
    fields = _feedback_fields(record)
    feedback_type = _text(fields.get("feedback_type"))
    candidate_id = _text(fields.get("candidate_id"))
    title = f"Feedback submitted: {feedback_type.lower()}"
    description = _text(fields.get("comments"))
    if candidate_id and not description:
        description = f"Candidate: {candidate_id}"
    event = _event(
        event_type="FEEDBACK_SUBMITTED",
        source=SOURCE_FEEDBACK,
        title=title,
        timestamp=_text(fields.get("created_at")),
        description=description,
        severity="info",
        metadata={
            "feedback_id": _text(fields.get("feedback_id")),
            "feedback_type": feedback_type,
            "candidate_id": candidate_id,
            "user_id": _text(fields.get("user_id")),
            "override_candidate_id": _text(fields.get("override_candidate_id")),
        },
    )
    return [event] if event else []


def _events_from_rca_record(record: dict[str, Any]) -> list[InvestigationTimelineEvent]:
    if _text(record.get("run_status")).lower() != "completed":
        return []
    title = "RCA completed"
    ticket_summary = _text(record.get("ticket_summary"))
    description = ticket_summary or "Investigation RCA run completed"
    bundle = record.get("relationship_ready_bundle") or {}
    target = _text(bundle.get("rca_target_file"))
    if target:
        description = f"{description} — top candidate: {target}".strip(" —")
    event = _event(
        event_type="RCA_COMPLETED",
        source=SOURCE_RCA,
        title=title,
        timestamp=_text(record.get("updated_at")) or _text(record.get("created_at")),
        description=description,
        severity="info",
        metadata={
            "run_id": _text(record.get("run_id")),
            "anomaly_id": _text(record.get("anomaly_id")),
            "ticket_key": _text(record.get("ticket_key")),
            "rca_target_file": target,
        },
    )
    return [event] if event else []


def _map_graph_node(
    row: dict[str, Any],
    *,
    investigation_created_at: str,
    ticket_props: dict[str, Any] | None,
) -> list[InvestigationTimelineEvent]:
    label = _primary_label([str(v) for v in (row.get("labels") or [])])
    props = dict(row.get("props") or {})
    ticket_dict = ticket_props if ticket_props else None

    if label == "JiraTicket":
        return _events_from_jira_ticket(ticket_dict or props, investigation_created_at=investigation_created_at)
    if label == "PullRequest":
        return _events_from_pull_request(props, source=SOURCE_GITHUB)
    if label == "MergeRequest":
        return _events_from_pull_request(props, source=SOURCE_GITLAB)
    if label == "Commit":
        return _events_from_commit(props)
    if label == "Build":
        return _events_from_build(props)
    if label == "Deployment":
        return _events_from_deployment(props)
    if label == "MetricEvent":
        return _events_from_metric(props)
    if label == "AlertEvent":
        return _events_from_alert(props)
    if label == "TraceEvent":
        return _events_from_trace(props)
    if label == "Pod":
        return _events_from_pod(props)
    if label == "Container":
        return _events_from_container(props)
    if label == "PagerDutyIncident":
        return _events_from_incident(props)
    if label == "Runbook":
        return _events_from_runbook(props)
    if label == "KnownIssue":
        return _events_from_known_issue(props)
    if label == "ArchitectureDocument":
        return _events_from_architecture_document(props)
    if label == "Feedback":
        return _events_from_feedback_record(props)
    return []


def _dedupe_events(events: list[InvestigationTimelineEvent]) -> list[InvestigationTimelineEvent]:
    seen: set[str] = set()
    unique: list[InvestigationTimelineEvent] = []
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        unique.append(event)
    return unique


def _apply_filters(
    events: list[InvestigationTimelineEvent],
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    event_type: str | None = None,
) -> list[InvestigationTimelineEvent]:
    start = _parse_timestamp(from_ts)
    end = _parse_timestamp(to_ts)
    wanted_type = _text(event_type).upper()

    filtered: list[InvestigationTimelineEvent] = []
    for event in events:
        if wanted_type and event.event_type.upper() != wanted_type:
            continue
        parsed = _parse_timestamp(event.timestamp)
        if start and parsed and parsed < start:
            continue
        if end and parsed and parsed > end:
            continue
        if (start or end) and parsed is None:
            continue
        filtered.append(event)
    return filtered


def build_investigation_timeline(
    client: Neo4jClient,
    investigation_id: str,
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    event_type: str | None = None,
) -> list[InvestigationTimelineEvent]:
    """Build a unified investigation timeline from graph and MCP-derived data."""
    if not investigation_exists(client, investigation_id):
        return []

    events: list[InvestigationTimelineEvent] = []
    context = _fetch_investigation_context(client, investigation_id)
    investigation_created_at = _text(context.get("investigation_created_at"))
    ticket_props = context.get("ticket_props")
    ticket_dict = dict(ticket_props) if isinstance(ticket_props, dict) else None

    if ticket_dict:
        events.extend(_events_from_jira_ticket(ticket_dict, investigation_created_at=investigation_created_at))

    for row in _fetch_graph_nodes(client, investigation_id):
        events.extend(
            _map_graph_node(
                row,
                investigation_created_at=investigation_created_at,
                ticket_props=ticket_dict,
            )
        )

    for record in get_feedback_for_investigation(client, investigation_id):
        events.extend(_events_from_feedback_record(record))

    try:
        store_record = _get_investigation_store().get_record(investigation_id) or {}
    except Exception:
        store_record = {}
    if store_record:
        events.extend(_events_from_rca_record(store_record))

    events = _dedupe_events(events)
    events = _apply_filters(events, from_ts=from_ts, to_ts=to_ts, event_type=event_type)
    events.sort(key=lambda event: (_timestamp_sort_key(event.timestamp), event.event_id))
    return events
