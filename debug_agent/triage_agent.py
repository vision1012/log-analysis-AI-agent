"""Triage agent: prioritizes and classifies anomalies."""

from __future__ import annotations

from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepResult, StepKind


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run triage agent step.

    Placeholder: prioritization logic when implemented.
    """
    return StepResult(
        step_kind=StepKind.TRIAGE,
        success=True,
        output={"placeholder": True, "anomaly_id": context.anomaly_id},
    )
