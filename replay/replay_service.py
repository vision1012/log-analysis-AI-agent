"""
Investigation replay service.

Builds ordered replay frames from timeline, graph, RCA, and feedback events.
Does not modify RCA ranking or GraphRAG behavior.
"""

from __future__ import annotations

from typing import Any

from graph.neo4j_client import Neo4jClient
from investigation.timeline_models import InvestigationTimelineEvent
from investigation.timeline_service import build_investigation_timeline
from replay.replay_models import InvestigationReplay, ReplayFrame

DEFAULT_PLAYBACK_SPEED = 1.0
MIN_PLAYBACK_SPEED = 0.25
MAX_PLAYBACK_SPEED = 4.0

EVENT_TYPE_TO_GRAPH_NODE: dict[str, str] = {
    "JIRA_CREATED": "JiraTicket",
    "PR_MERGED": "PullRequest",
    "COMMIT_PUSHED": "Commit",
    "BUILD_STARTED": "Build",
    "BUILD_COMPLETED": "Build",
    "DEPLOYMENT_STARTED": "Deployment",
    "DEPLOYMENT_COMPLETED": "Deployment",
    "METRIC_SPIKE": "MetricEvent",
    "ALERT_TRIGGERED": "AlertEvent",
    "TRACE_FAILURE": "TraceEvent",
    "POD_RESTART": "Pod",
    "OOM_KILLED": "Container",
    "INCIDENT_OPENED": "PagerDutyIncident",
    "INCIDENT_ACKNOWLEDGED": "PagerDutyIncident",
    "RUNBOOK_MATCHED": "Runbook",
    "FEEDBACK_SUBMITTED": "Feedback",
    "RCA_COMPLETED": "Investigation",
}

METADATA_ID_KEYS = (
    "issue_key",
    "alert_id",
    "build_id",
    "deployment_id",
    "incident_id",
    "runbook_id",
    "feedback_id",
    "trace_id",
    "pod_id",
    "container_id",
    "metric_id",
    "sha",
    "run_id",
)


def _clamp_playback_speed(value: float | None) -> float:
    if value is None:
        return DEFAULT_PLAYBACK_SPEED
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_PLAYBACK_SPEED
    return max(MIN_PLAYBACK_SPEED, min(MAX_PLAYBACK_SPEED, speed))


def _entity_id(metadata: dict[str, Any]) -> str:
    for key in METADATA_ID_KEYS:
        value = metadata.get(key)
        if value:
            return str(value)
    return ""


def _graph_delta_for_event(event: InvestigationTimelineEvent) -> dict[str, Any]:
    """Describe graph change implied by a timeline event."""
    metadata = dict(event.metadata or {})
    node_type = EVENT_TYPE_TO_GRAPH_NODE.get(event.event_type, "Unknown")

    if event.event_type == "RCA_COMPLETED":
        return {
            "action": "update",
            "node_type": node_type,
            "node_id": metadata.get("run_id") or event.event_id,
            "changes": {
                "rca_status": "completed",
                "rca_target_file": metadata.get("rca_target_file", ""),
            },
        }

    if event.event_type == "FEEDBACK_SUBMITTED":
        return {
            "action": "add",
            "node_type": node_type,
            "node_id": _entity_id(metadata) or event.event_id,
            "relationship": "HAS_FEEDBACK",
            "properties": {
                "feedback_type": metadata.get("feedback_type", ""),
                "candidate_id": metadata.get("candidate_id", ""),
            },
        }

    if event.event_type in {"BUILD_STARTED", "DEPLOYMENT_STARTED", "INCIDENT_ACKNOWLEDGED"}:
        return {
            "action": "update",
            "node_type": node_type,
            "node_id": _entity_id(metadata) or event.event_id,
            "changes": {"status": metadata.get("status", event.event_type.lower())},
            "properties": metadata,
        }

    return {
        "action": "add",
        "node_type": node_type,
        "node_id": _entity_id(metadata) or event.event_id,
        "properties": metadata,
    }


def _timeline_event_to_frame(event: InvestigationTimelineEvent, position: int) -> ReplayFrame:
    return ReplayFrame(
        frame_id=f"frame:{event.event_id}",
        timestamp=event.timestamp,
        event_type=event.event_type,
        title=event.title,
        description=event.description,
        source=event.source,
        severity=event.severity,
        graph_delta=_graph_delta_for_event(event),
        timeline_position=position,
    )


def build_replay(
    client: Neo4jClient,
    investigation_id: str,
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    event_type: str | None = None,
    playback_speed: float | None = None,
) -> InvestigationReplay:
    """
    Build ordered replay frames for an investigation.

    Frame sources: timeline events (graph, RCA completion, feedback).
    """
    events = build_investigation_timeline(
        client,
        investigation_id,
        from_ts=from_ts,
        to_ts=to_ts,
        event_type=event_type,
    )
    speed = _clamp_playback_speed(playback_speed)
    frames = [_timeline_event_to_frame(event, index) for index, event in enumerate(events)]
    return InvestigationReplay(
        investigation_id=investigation_id,
        frames=frames,
        playback_speed=speed,
        total_frames=len(frames),
    )
