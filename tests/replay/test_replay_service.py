"""Tests for investigation replay service."""

from __future__ import annotations

from typing import Any
from unittest.mock import ANY, patch

from investigation.timeline_models import InvestigationTimelineEvent
from replay.replay_service import build_replay


class _MockClient:
    def __init__(self, *, exists: bool = True) -> None:
        self.exists = exists

    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "RETURN i.id AS id LIMIT 1" in query:
            return [{"id": parameters.get("investigation_id")}] if self.exists else []
        return []


def _sample_events() -> list[InvestigationTimelineEvent]:
    return [
        InvestigationTimelineEvent(
            event_id="evt-1",
            timestamp="2024-01-01T08:00:00Z",
            event_type="JIRA_CREATED",
            source="Jira",
            title="Auth outage",
            metadata={"issue_key": "OPS-1"},
        ),
        InvestigationTimelineEvent(
            event_id="evt-2",
            timestamp="2024-01-01T09:00:00Z",
            event_type="COMMIT_PUSHED",
            source="GitHub",
            title="Fix auth handler",
            metadata={"sha": "abc123"},
        ),
        InvestigationTimelineEvent(
            event_id="evt-3",
            timestamp="2024-01-01T10:00:00Z",
            event_type="ALERT_TRIGGERED",
            source="Datadog",
            title="Error rate high",
            severity="high",
            metadata={"alert_id": "alert-1", "service": "auth-service"},
        ),
        InvestigationTimelineEvent(
            event_id="evt-4",
            timestamp="2024-01-01T11:00:00Z",
            event_type="RCA_COMPLETED",
            source="RCA",
            title="RCA completed",
            metadata={"run_id": "run-1", "rca_target_file": "/srv/auth/handler.py"},
        ),
        InvestigationTimelineEvent(
            event_id="evt-5",
            timestamp="2024-01-01T12:00:00Z",
            event_type="FEEDBACK_SUBMITTED",
            source="Feedback",
            title="Feedback submitted: confirmed",
            metadata={
                "feedback_id": "fb-1",
                "feedback_type": "CONFIRMED",
                "candidate_id": "/srv/auth/handler.py",
            },
        ),
    ]


@patch("replay.replay_service.build_investigation_timeline", return_value=[])
def test_build_replay_returns_empty_when_no_events(mock_timeline) -> None:
    replay = build_replay(_MockClient(), "inv-empty")
    assert replay.investigation_id == "inv-empty"
    assert replay.frames == []
    assert replay.total_frames == 0
    assert replay.playback_speed == 1.0


@patch("replay.replay_service.build_investigation_timeline", return_value=_sample_events())
def test_build_replay_orders_frames_chronologically(mock_timeline) -> None:
    replay = build_replay(_MockClient(), "inv-1")

    assert replay.total_frames == 5
    assert len(replay.frames) == 5
    assert replay.frames[0].event_type == "JIRA_CREATED"
    assert replay.frames[1].event_type == "COMMIT_PUSHED"
    assert replay.frames[2].event_type == "ALERT_TRIGGERED"
    assert replay.frames[3].event_type == "RCA_COMPLETED"
    assert replay.frames[4].event_type == "FEEDBACK_SUBMITTED"

    for index, frame in enumerate(replay.frames):
        assert frame.timeline_position == index
        assert frame.frame_id.startswith("frame:")


@patch("replay.replay_service.build_investigation_timeline", return_value=_sample_events())
def test_build_replay_includes_graph_deltas(mock_timeline) -> None:
    replay = build_replay(_MockClient(), "inv-1")

    assert replay.frames[0].graph_delta["action"] == "add"
    assert replay.frames[0].graph_delta["node_type"] == "JiraTicket"
    assert replay.frames[0].graph_delta["node_id"] == "OPS-1"

    assert replay.frames[2].graph_delta["node_type"] == "AlertEvent"
    assert replay.frames[2].graph_delta["node_id"] == "alert-1"

    assert replay.frames[3].graph_delta["action"] == "update"
    assert replay.frames[3].graph_delta["changes"]["rca_status"] == "completed"

    assert replay.frames[4].graph_delta["node_type"] == "Feedback"
    assert replay.frames[4].graph_delta["relationship"] == "HAS_FEEDBACK"


@patch("replay.replay_service.build_investigation_timeline", return_value=_sample_events())
def test_build_replay_passes_timeline_filters(mock_timeline) -> None:
    build_replay(
        _MockClient(),
        "inv-1",
        from_ts="2024-01-01T09:00:00Z",
        to_ts="2024-01-01T11:00:00Z",
        event_type="ALERT_TRIGGERED",
    )
    mock_timeline.assert_called_once_with(
        ANY,
        "inv-1",
        from_ts="2024-01-01T09:00:00Z",
        to_ts="2024-01-01T11:00:00Z",
        event_type="ALERT_TRIGGERED",
    )


@patch("replay.replay_service.build_investigation_timeline", return_value=_sample_events())
def test_build_replay_clamps_playback_speed(mock_timeline) -> None:
    replay = build_replay(_MockClient(), "inv-1", playback_speed=10.0)
    assert replay.playback_speed == 4.0

    replay_slow = build_replay(_MockClient(), "inv-1", playback_speed=0.1)
    assert replay_slow.playback_speed == 0.25
