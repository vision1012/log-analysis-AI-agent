"""
Plan Models

Pydantic models for execution plans.
A Plan is a validated structure that specifies which tools to call and with what arguments.
"""

from __future__ import annotations

from typing import List, Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from agent.runtime.job_models import ToolCall


PlanMode = Literal["heuristic", "llm"]


class Plan(BaseModel):
    """
    Structured execution plan for a job.
    
    Contains:
    - List of ToolCall objects (validated)
    - Planning metadata (mode, reasoning, timestamp)
    - No free-form text - all structured
    """

    model_config = ConfigDict(extra="forbid")

    mode: PlanMode = Field(
        ...,
        description="Planning mode used: 'heuristic' or 'llm'.",
    )
    tool_calls: List[ToolCall] = Field(
        ...,
        description="List of tool calls to execute, in order.",
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Optional reasoning text explaining the plan (from LLM or heuristic).",
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="When this plan was created.",
    )
    planner_version: str = Field(
        default="1.0.0",
        description="Version of the planner that generated this plan.",
    )

    def model_dump(self, **kwargs) -> dict:
        """Override to ensure datetime serialization."""
        data = super().model_dump(**kwargs)
        if isinstance(data.get("created_at"), datetime):
            data["created_at"] = data["created_at"].isoformat()
        return data
