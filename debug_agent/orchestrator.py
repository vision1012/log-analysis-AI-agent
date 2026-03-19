"""Orchestrator: runs planned debug steps and aggregates results."""

from __future__ import annotations

from typing import Any, Optional

from debug_agent.planner import plan_steps
from debug_agent.shared_types import DebugContext, StepKind, StepResult


def run_debug_session(
    anomaly_id: str,
    *,
    run_id: Optional[str] = None,
    user_hint: Optional[str] = None,
) -> dict[str, Any]:
    """
    Run a full debug session for an anomaly.

    Plans steps, executes them, and returns aggregated results.
    """
    context = DebugContext(anomaly_id=anomaly_id, run_id=run_id)
    steps = plan_steps(context, user_hint=user_hint)
    results: list[StepResult] = []

    for step_desc in steps:
        kind = step_desc.get("kind", "")
        params = step_desc.get("params") or {}
        result = _execute_step(kind, context, params)
        results.append(result)

    return {
        "anomaly_id": anomaly_id,
        "run_id": run_id,
        "steps": [
            {
                "kind": r.step_kind.value,
                "success": r.success,
                "output": r.output,
                "error": r.error,
            }
            for r in results
        ],
    }


_AGENT_MAP = {
    StepKind.RCA.value: "debug_agent.rca_agent",
    StepKind.EVIDENCE.value: "debug_agent.evidence_agent",
    StepKind.EXPLANATION.value: "debug_agent.explanation_agent",
    StepKind.TRIAGE.value: "debug_agent.triage_agent",
    StepKind.MEMORY.value: "debug_agent.memory_agent",
    StepKind.REMEDIATION.value: "debug_agent.remediation_agent",
    StepKind.REPORTING.value: "debug_agent.reporting_agent",
}


def _execute_step(
    kind: str,
    context: DebugContext,
    params: dict[str, Any],
) -> StepResult:
    """Execute a single step by delegating to the appropriate agent."""
    try:
        step_kind = StepKind(kind)
    except ValueError:
        return StepResult(step_kind=StepKind.RCA, success=False, error=f"Unknown step kind: {kind}")

    module_path = _AGENT_MAP.get(kind)
    if not module_path:
        return StepResult(step_kind=step_kind, success=False, error=f"No agent for kind: {kind}")

    try:
        import importlib
        mod = importlib.import_module(module_path)
        return mod.run(context, params=params)
    except Exception as e:
        return StepResult(step_kind=step_kind, success=False, error=str(e))
