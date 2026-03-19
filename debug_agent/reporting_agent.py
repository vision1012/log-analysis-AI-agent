"""Reporting agent: aggregates and formats debug session output."""

from __future__ import annotations

from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepResult, StepKind


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run reporting agent step.

    Placeholder: output formatting when implemented.
    """
    return StepResult(
        step_kind=StepKind.REPORTING,
        success=True,
        output={"placeholder": True, "anomaly_id": context.anomaly_id},
    )
