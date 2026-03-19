"""Evidence agent: gathers and structures evidence from graph and bundles."""

from __future__ import annotations

from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepResult, StepKind


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run evidence agent step.

    Placeholder: delegates to evidence summarization when implemented.
    """
    return StepResult(
        step_kind=StepKind.EVIDENCE,
        success=True,
        output={"placeholder": True, "anomaly_id": context.anomaly_id},
    )
