"""Conference demo mode models."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class DemoScenario(BaseModel):
    """Pre-built realistic investigation scenario for conference demos."""

    scenario_id: str
    title: str
    description: str
    service_name: str
    severity: str
    ticket_key: str
    root_cause: str
    resolution: str
    confidence: float
    timeline_events: List[dict[str, Any]] = Field(default_factory=list)
    graph_entities: dict[str, Any] = Field(default_factory=dict)
    similar_incidents: List[dict[str, Any]] = Field(default_factory=list)


class DemoFeedbackSeed(BaseModel):
    """Optional engineer feedback to seed after launch."""

    feedback_type: str = "CONFIRMED"
    candidate_id: str = ""
    override_candidate_id: str = ""
    comments: str = ""
    user_id: str = "demo-engineer"


class DemoLaunchResult(BaseModel):
    """Result of launching a demo scenario into a live investigation workspace."""

    scenario_id: str
    investigation_id: str
    ticket_key: str
    service_name: str
    root_cause: str
    confidence: float
    resolution: str
    graph_nodes: int = 0
    graph_relationships: int = 0
    timeline_event_count: int = 0
    feedback_seeded: bool = False
    rca_completed: bool = True
