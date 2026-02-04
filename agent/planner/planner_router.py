"""
Planner Router

Routes planning requests to the appropriate planner (heuristic or LLM).
Returns a validated Plan object.
"""

from __future__ import annotations

from typing import List, Literal
from agent.runtime.job_models import JobRequest
from agent.runtime.tool_registry import list_tools
from agent.planner.plan_models import Plan, PlanMode
from agent.planner.heuristic_planner import plan_heuristic
from agent.planner.llm_planner import plan_llm


def create_plan(
    request: JobRequest,
    mode: Literal["heuristic", "llm"] = "heuristic",
) -> Plan:
    """
    Create a structured execution plan based on the job request.

    Routes to heuristic or LLM planner based on mode.
    Returns a validated Plan object (Pydantic model).

    Args:
        request: JobRequest containing query and file paths.
        mode: Planning mode - "heuristic" (rule-based) or "llm" (LLM-based).

    Returns:
        Plan object with validated tool calls.

    Raises:
        ValueError: If mode is invalid.
    """
    available_tools = list(list_tools().keys())

    if mode == "heuristic":
        tool_calls = plan_heuristic(request, available_tools)
        reasoning = f"Heuristic planning: matched keywords in query '{request.query}' to {len(tool_calls)} tool(s)"
    elif mode == "llm":
        tool_calls = plan_llm(request, available_tools)
        reasoning = f"LLM planning: analyzed query '{request.query}' and selected {len(tool_calls)} tool(s)"
    else:
        raise ValueError(f"Unknown planning mode: {mode}. Must be 'heuristic' or 'llm'")

    return Plan(
        mode=mode,
        tool_calls=tool_calls,
        reasoning=reasoning,
    )
