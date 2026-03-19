"""Planner: deterministic, rule-based execution plan for debug-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from debug_agent.shared_types import DebugContext, StepKind


@dataclass
class PlanStep:
    """Single step in an investigation plan."""
    step_name: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    optional: bool = False


def _explanation_enabled(context: DebugContext, user_hint: Optional[str]) -> bool:
    """Rule-based switch for explanation step."""
    meta = context.metadata or {}
    if meta.get("enable_explanation") is False:
        return False
    hint = (user_hint or "").lower()
    if "skip explanation" in hint or "disable explanation" in hint or "no explanation" in hint:
        return False
    return True


def _has_graph_history(context: DebugContext) -> bool:
    """Whether graph history is available for memory lookup."""
    meta = context.metadata or {}
    # Caller can explicitly disable memory when running in partial/offline mode.
    if meta.get("has_graph_data") is False:
        return False
    if meta.get("skip_memory") is True:
        return False
    return True


def _build_wave_1_steps(context: DebugContext, user_hint: Optional[str]) -> list[PlanStep]:
    """
    Build Wave 1 plan:
      1) Triage
      2) RCA
      3) Evidence
      4) Memory (optional skip if no graph data)
      5) Explanation (optional skip if disabled)
    """
    steps: list[PlanStep] = [
        PlanStep(
            step_name="triage_agent",
            kind=StepKind.TRIAGE.value,
            params={},
            depends_on=[],
            optional=True,  # triage enriches context; failures should not block RCA.
        ),
        PlanStep(
            step_name="rca_agent",
            kind=StepKind.RCA.value,
            params={},
            depends_on=[StepKind.TRIAGE.value],
            optional=False,  # source-of-truth step
        ),
        PlanStep(
            step_name="evidence_agent",
            kind=StepKind.EVIDENCE.value,
            params={},
            depends_on=[StepKind.RCA.value],
            optional=True,  # continue with partial evidence if needed
        ),
    ]

    has_graph_data = _has_graph_history(context)
    explanation_enabled = _explanation_enabled(context, user_hint)

    if has_graph_data:
        steps.append(
            PlanStep(
                step_name="memory_agent",
                kind=StepKind.MEMORY.value,
                params={},
                depends_on=[StepKind.EVIDENCE.value],
                optional=True,
            )
        )

    if explanation_enabled:
        depends = [StepKind.EVIDENCE.value]
        if has_graph_data:
            depends.append(StepKind.MEMORY.value)
        steps.append(
            PlanStep(
                step_name="explanation_agent",
                kind=StepKind.EXPLANATION.value,
                params={},
                depends_on=depends,
                optional=True,  # must degrade safely if provider/LLM unavailable
            )
        )

    return steps


def plan_steps(
    context: DebugContext,
    *,
    user_hint: Optional[str] = None,
    wave: str = "wave_1",
) -> list[dict[str, Any]]:
    """
    Build deterministic investigation plan for the given context.

    Rule-based behavior:
    - Always include triage, RCA, evidence
    - Include memory unless graph history is unavailable
    - Include explanation unless explicitly disabled
    """
    if wave != "wave_1":
        wave = "wave_1"
    steps = _build_wave_1_steps(context, user_hint)

    # Inject context into params (copy to avoid mutating shared steps)
    out: list[dict[str, Any]] = []
    for s in steps:
        params = dict(s.params)
        params.setdefault("anomaly_id", context.anomaly_id)
        if context.run_id:
            params.setdefault("run_id", context.run_id)
        out.append(
            {
                "step_name": s.step_name,
                "kind": s.kind,  # retained for orchestrator compatibility
                "params": params,
                "depends_on": s.depends_on,
                "optional": s.optional,
            }
        )
    return out
