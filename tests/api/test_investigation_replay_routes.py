"""API route tests for investigation replay mode."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.services.investigation_graph_service import InvestigationGraphNotFoundError
from replay.replay_models import InvestigationReplay, ReplayFrame


def _replay() -> InvestigationReplay:
    return InvestigationReplay(
        investigation_id="inv-1",
        frames=[
            ReplayFrame(
                frame_id="frame:evt-1",
                timestamp="2024-01-01T09:00:00Z",
                event_type="ALERT_TRIGGERED",
                title="Error rate high",
                source="Datadog",
                severity="high",
                graph_delta={"action": "add", "node_type": "AlertEvent", "node_id": "alert-1"},
                timeline_position=0,
            )
        ],
        playback_speed=1.0,
        total_frames=1,
    )


def test_investigation_replay_endpoint_success() -> None:
    from api.routes.investigation_graph import get_investigation_replay_endpoint

    with patch(
        "api.routes.investigation_graph.fetch_investigation_replay",
        return_value=_replay(),
    ):
        body = asyncio.run(
            get_investigation_replay_endpoint(
                "inv-1",
                from_ts=None,
                to_ts=None,
                event_type=None,
                playback_speed=1.0,
            )
        )

    assert body["investigation_id"] == "inv-1"
    assert body["total_frames"] == 1
    assert body["playback_speed"] == 1.0
    assert body["frames"][0]["event_type"] == "ALERT_TRIGGERED"
    assert body["frames"][0]["timeline_position"] == 0


def test_investigation_replay_endpoint_not_found() -> None:
    from api.routes.investigation_graph import get_investigation_replay_endpoint

    with patch(
        "api.routes.investigation_graph.fetch_investigation_replay",
        side_effect=InvestigationGraphNotFoundError("missing"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                get_investigation_replay_endpoint(
                    "missing",
                    from_ts=None,
                    to_ts=None,
                    event_type=None,
                    playback_speed=1.0,
                )
            )

    assert exc.value.status_code == 404


def test_investigation_replay_endpoint_passes_filters() -> None:
    from api.routes.investigation_graph import get_investigation_replay_endpoint

    with patch(
        "api.routes.investigation_graph.fetch_investigation_replay",
        return_value=_replay(),
    ) as mocked:
        asyncio.run(
            get_investigation_replay_endpoint(
                "inv-1",
                from_ts="2024-01-01T00:00:00Z",
                to_ts="2024-01-02T00:00:00Z",
                event_type="ALERT_TRIGGERED",
                playback_speed=2.0,
            )
        )

    mocked.assert_called_once_with(
        "inv-1",
        from_ts="2024-01-01T00:00:00Z",
        to_ts="2024-01-02T00:00:00Z",
        event_type="ALERT_TRIGGERED",
        playback_speed=2.0,
    )
