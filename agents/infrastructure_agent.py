"""Kubernetes infrastructure analysis agent."""

from __future__ import annotations

from agents.agent_models import AgentFinding, AgentInvestigationContext
from agents.base_agent import BaseAgent

_INFRA_EVENT_TYPES = {"POD_RESTART", "OOM_KILLED"}


class InfrastructureAgent(BaseAgent):
    name = "infrastructure"

    def investigate(self, context: AgentInvestigationContext) -> AgentFinding:
        observations: list[str] = []
        suspicious: list[str] = []
        correlations: list[str] = []

        infra_events = [
            event for event in context.timeline_events if event.event_type in _INFRA_EVENT_TYPES
        ]
        if infra_events:
            observations.append(f"Detected {len(infra_events)} Kubernetes infrastructure event(s).")
        else:
            observations.append("No pod restart or OOM events in timeline.")

        for event in infra_events:
            observations.append(f"{event.event_type}: {event.title}")
            suspicious.append(event.title)
            if event.event_type == "OOM_KILLED":
                correlations.append("oom_killed")
            if event.event_type == "POD_RESTART":
                correlations.append("pod_restart")

        node_mentions = [
            event
            for event in context.timeline_events
            if "node" in event.description.lower() or "node" in event.title.lower()
        ]
        if node_mentions:
            observations.append("Node pressure or node failure signals present in timeline.")
            correlations.append("node_pressure")

        confidence = 0.15 + 0.25 * len(infra_events) + 0.1 * len(node_mentions)
        summary = (
            f"Infrastructure analysis found {len(infra_events)} pod/container incident(s)."
            if infra_events
            else "No significant Kubernetes instability detected."
        )
        return AgentFinding(
            agent_name=self.name,
            summary=summary,
            key_observations=observations,
            suspicious_items=suspicious,
            correlations=correlations,
            confidence=round(min(0.95, confidence), 4),
            evidence={"infra_event_count": len(infra_events)},
        )
