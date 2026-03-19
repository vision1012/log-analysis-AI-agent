"""Explanation agent: generates natural-language explanations from RCA results."""

from __future__ import annotations

from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepResult, StepKind


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Run explanation agent step.

    Placeholder: delegates to GraphRAG explanation layer when implemented.
    """
    return StepResult(
        step_kind=StepKind.EXPLANATION,
        success=True,
        output={"placeholder": True, "anomaly_id": context.anomaly_id},
    )
