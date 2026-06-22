"""Deployment and release history analysis agent."""

from __future__ import annotations

from agents.agent_models import AgentFinding, AgentInvestigationContext
from agents.base_agent import BaseAgent


class DeploymentAgent(BaseAgent):
    name = "deployment"

    def investigate(self, context: AgentInvestigationContext) -> AgentFinding:
        observations: list[str] = []
        suspicious: list[str] = []
        correlations: list[str] = []

        builds = context.builds
        deployments = context.deployments

        if builds:
            observations.append(f"Found {len(builds)} related build(s).")
            for build in builds[:3]:
                status = str(build.get("status") or "").upper()
                number = build.get("build_number")
                observations.append(f"Build #{number} status={status or 'unknown'}.")
                if status in {"FAILURE", "FAILED", "UNSTABLE"}:
                    suspicious.append(f"Build #{number} failed.")
        else:
            observations.append("No build nodes linked to investigation.")

        if deployments:
            observations.append(f"Found {len(deployments)} deployment(s).")
            for dep in deployments[:3]:
                status = (dep.status or "").lower()
                observations.append(
                    f"Deployment {dep.deployment_id} env={dep.environment} status={status or 'unknown'}."
                )
                if status in {"failed", "failure", "rolled_back", "aborted"}:
                    suspicious.append(f"Deployment {dep.deployment_id} indicates rollback risk.")
                    correlations.append("failed_deployment")
                if dep.commit_sha:
                    correlations.append(f"deploy_commit:{dep.commit_sha[:8]}")
        else:
            observations.append("No deployment nodes linked to investigation.")

        rollback_indicators = [
            event.title
            for event in context.timeline_events
            if "rollback" in event.title.lower() or "revert" in event.description.lower()
        ]
        if rollback_indicators:
            suspicious.extend(rollback_indicators)
            correlations.append("rollback_indicator_in_timeline")

        confidence = 0.2
        if deployments:
            confidence += 0.35
        if builds:
            confidence += 0.2
        if suspicious:
            confidence += 0.15

        summary = (
            f"Deployment analysis reviewed {len(builds)} build(s) and "
            f"{len(deployments)} deployment(s)."
        )
        return AgentFinding(
            agent_name=self.name,
            summary=summary,
            key_observations=observations,
            suspicious_items=suspicious,
            correlations=correlations,
            confidence=round(min(0.95, confidence), 4),
            evidence={"build_count": len(builds), "deployment_count": len(deployments)},
        )
