"""RCA agent: interfaces with deterministic RCA for anomaly analysis."""

from __future__ import annotations

from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepResult, StepKind


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run RCA agent step.

    Placeholder: delegates to deterministic RCA when implemented.
    """
    return StepResult(
        step_kind=StepKind.RCA,
        success=True,
        output={"placeholder": True, "anomaly_id": context.anomaly_id},
    )
