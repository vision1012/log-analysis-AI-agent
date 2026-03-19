"""Remediation agent: suggests advisory patch directions and fixes."""

from __future__ import annotations

from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepResult, StepKind


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run remediation agent step.

    Placeholder: advisory patch suggestions when implemented.
    """
    return StepResult(
        step_kind=StepKind.REMEDIATION,
        success=True,
        output={"placeholder": True, "anomaly_id": context.anomaly_id},
    )
