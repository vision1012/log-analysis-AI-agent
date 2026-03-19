"""Memory agent: maintains session and historical context."""

from __future__ import annotations

from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepResult, StepKind


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run memory agent step.

    Placeholder: session/historical context when implemented.
    """
    return StepResult(
        step_kind=StepKind.MEMORY,
        success=True,
        output={"placeholder": True, "anomaly_id": context.anomaly_id},
    )
