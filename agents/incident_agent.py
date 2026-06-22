"""Alert and incident management analysis agent."""

from __future__ import annotations

from agents.agent_models import AgentFinding, AgentInvestigationContext
from agents.base_agent import BaseAgent


class IncidentAgent(BaseAgent):
    name = "incident"

    def investigate(self, context: AgentInvestigationContext) -> AgentFinding:
        observations: list[str] = []
        suspicious: list[str] = []
        correlations: list[str] = []

        alerts = context.alerts
        incidents = context.incidents

        if alerts:
            observations.append(f"Found {len(alerts)} Datadog alert(s).")
            for alert in alerts[:3]:
                observations.append(
                    f"Alert '{alert.title}' severity={alert.severity or 'unknown'} service={alert.service}."
                )
                if (alert.severity or "").lower() in {"critical", "high", "sev1", "sev2"}:
                    suspicious.append(alert.title)
                    correlations.append(f"alert_severity:{alert.severity}")
        else:
            observations.append("No alert nodes linked to investigation.")

        if incidents:
            observations.append(f"Found {len(incidents)} PagerDuty incident(s).")
            for incident in incidents[:3]:
                observations.append(
                    f"Incident #{incident.incident_number} status={incident.status} urgency={incident.urgency}."
                )
                if (incident.status or "").lower() in {"triggered", "acknowledged"}:
                    correlations.append("active_pagerduty_incident")
                if (incident.urgency or "").lower() == "high":
                    suspicious.append(incident.title)
        else:
            observations.append("No PagerDuty incidents linked to investigation.")

        if alerts and incidents:
            correlations.append("alert_escalated_to_pagerduty")

        confidence = 0.2 + 0.25 * bool(alerts) + 0.25 * bool(incidents) + 0.1 * len(suspicious)
        summary = (
            f"Incident analysis reviewed {len(alerts)} alert(s) and {len(incidents)} PagerDuty incident(s)."
        )
        return AgentFinding(
            agent_name=self.name,
            summary=summary,
            key_observations=observations,
            suspicious_items=suspicious,
            correlations=correlations,
            confidence=round(min(0.95, confidence), 4),
            evidence={"alert_count": len(alerts), "incident_count": len(incidents)},
        )
