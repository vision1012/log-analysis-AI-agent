"""Timeline analysis agent."""

from __future__ import annotations

from datetime import datetime, timezone

from agents.agent_models import AgentFinding, AgentInvestigationContext
from agents.base_agent import BaseAgent


def _parse_ts(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


class TimelineAgent(BaseAgent):
    name = "timeline"

    def investigate(self, context: AgentInvestigationContext) -> AgentFinding:
        events = sorted(
            context.timeline_events,
            key=lambda event: _parse_ts(event.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
        )
        observations: list[str] = []
        suspicious: list[str] = []
        correlations: list[str] = []

        if not events:
            return AgentFinding(
                agent_name=self.name,
                summary="No timeline events available for temporal analysis.",
                confidence=0.0,
            )

        observations.append(f"Analyzed {len(events)} timeline events.")

        deploy_types = {"DEPLOYMENT_STARTED", "DEPLOYMENT_COMPLETED"}
        alert_types = {"ALERT_TRIGGERED", "METRIC_SPIKE", "TRACE_FAILURE"}
        incident_types = {"INCIDENT_OPENED", "INCIDENT_ACKNOWLEDGED"}

        deploy_times = [e for e in events if e.event_type in deploy_types and e.timestamp]
        alert_times = [e for e in events if e.event_type in alert_types and e.timestamp]
        incident_times = [e for e in events if e.event_type in incident_types and e.timestamp]

        for idx in range(len(events) - 1):
            current = events[idx]
            nxt = events[idx + 1]
            if current.event_type == "DEPLOYMENT_COMPLETED" and nxt.event_type in alert_types:
                suspicious.append(
                    f"Alert '{nxt.title}' followed deployment '{current.title}'."
                )
                correlations.append("deployment_precedes_alert")

        if deploy_times and alert_times:
            first_deploy = _parse_ts(deploy_times[0].timestamp)
            first_alert = _parse_ts(alert_times[0].timestamp)
            if first_deploy and first_alert and first_alert > first_deploy:
                delta_min = int((first_alert - first_deploy).total_seconds() / 60)
                correlations.append(f"alert_within_{delta_min}m_of_deployment")
                observations.append(f"First alert occurred {delta_min} minutes after deployment.")

        if incident_times:
            observations.append(
                f"PagerDuty incident activity detected ({len(incident_times)} event(s))."
            )

        sequence = " → ".join(event.event_type for event in events[:6])
        if sequence:
            observations.append(f"Opening sequence: {sequence}")

        confidence = min(0.95, 0.35 + 0.1 * len(correlations) + 0.05 * len(suspicious))
        summary = (
            f"Timeline analysis identified {len(suspicious)} suspicious sequence(s) "
            f"and {len(correlations)} temporal correlation(s)."
        )
        return AgentFinding(
            agent_name=self.name,
            summary=summary,
            key_observations=observations,
            suspicious_items=suspicious,
            correlations=correlations,
            confidence=round(confidence, 4),
            evidence={"event_count": len(events)},
        )
