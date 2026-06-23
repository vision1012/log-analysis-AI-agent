"""Investigation timeline workspace models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InvestigationTimelineEvent(BaseModel):
    """Single chronological event in an investigation timeline."""

    event_id: str
    timestamp: str
    event_type: str
    source: str
    title: str
    description: str = ""
    severity: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
