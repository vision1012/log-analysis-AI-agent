"""Investigation replay models."""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field


class ReplayFrame(BaseModel):
    """Single chronological frame in an investigation replay."""

    frame_id: str
    timestamp: str
    event_type: str
    title: str
    description: str = ""
    source: str
    severity: str = ""
    graph_delta: dict[str, Any] = Field(default_factory=dict)
    timeline_position: int = 0


class InvestigationReplay(BaseModel):
    """Ordered replay of investigation events."""

    investigation_id: str
    frames: List[ReplayFrame] = Field(default_factory=list)
    playback_speed: float = 1.0
    total_frames: int = 0
