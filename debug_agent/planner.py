"""Planner: deterministic investigation plan. No LLM. Defines execution order and dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepKind


@dataclass
class PlanStep:
    """Single step in an investigation plan."""
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    optional: bool = False


# Wave 1: RCA -> Evidence -> Explanation
# - RCA: source of truth; must run first
# - Evidence: summarizes bundles from RCA; depends on RCA
# - Explanation: GraphRAG layer; depends on RCA (and uses evidence internally)
WAVE_1_STEPS = [
    PlanStep(
        kind=StepKind.RCA.value,
        params={},
        depends_on=[],
        optional=False,
    ),
    PlanStep(
        kind=StepKind.EVIDENCE.value,
        params={},
        depends_on=[StepKind.RCA.value],
        optional=True,  # Safe fallback: Evidence can return empty if RCA failed
    ),
    PlanStep(
        kind=StepKind.EXPLANATION.value,
        params={},
        depends_on=[StepKind.RCA.value],
        optional=True,  # Safe fallback: Explanation returns fallback if RCA/LLM failed
    ),
]


def plan_steps(
    context: DebugContext,
    *,
    user_hint: Optional[str] = None,
    wave: str = "wave_1",
) -> list[dict[str, Any]]:
    """
    Build deterministic investigation plan for the given context.

    Execution order: RCA -> Evidence -> Explanation.
    Dependencies: Evidence and Explanation depend on RCA.
    Safe fallback: Evidence and Explanation are optional; they return partial
    results if dependencies failed.

    Returns ordered list of step descriptors for the orchestrator.
    """
    steps = list(WAVE_1_STEPS)

    # Inject context into params (copy to avoid mutating shared steps)
    out: list[dict[str, Any]] = []
    for s in steps:
        params = dict(s.params)
        params.setdefault("anomaly_id", context.anomaly_id)
        if context.run_id:
            params.setdefault("run_id", context.run_id)
        out.append({
            "kind": s.kind,
            "params": params,
            "depends_on": s.depends_on,
            "optional": s.optional,
        })
    return out
