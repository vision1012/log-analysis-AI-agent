"""Runbook, known issue, and historical investigation agent."""

from __future__ import annotations

from agents.agent_models import AgentFinding, AgentInvestigationContext
from agents.base_agent import BaseAgent


class KnowledgeAgent(BaseAgent):
    name = "knowledge"

    def investigate(self, context: AgentInvestigationContext) -> AgentFinding:
        observations: list[str] = []
        suspicious: list[str] = []
        correlations: list[str] = []

        runbooks = context.runbooks
        known_issues = context.known_issues
        similar = context.similar_investigations

        if runbooks:
            observations.append(f"Matched {len(runbooks)} runbook(s).")
            for doc in runbooks[:2]:
                observations.append(f"Runbook: {doc.title}")
                correlations.append(f"runbook:{doc.runbook_id}")
        else:
            observations.append("No runbooks matched for service context.")

        if known_issues:
            observations.append(f"Found {len(known_issues)} known issue match(es).")
            for issue in known_issues[:2]:
                suspicious.append(issue.title)
                observations.append(f"Known issue: {issue.title} — {issue.workaround}")
                correlations.append(f"known_issue:{issue.known_issue_id}")
        else:
            observations.append("No known issues linked to alerts.")

        if similar:
            observations.append(f"Identified {len(similar)} similar historical investigation(s).")
            top = similar[0]
            observations.append(
                f"Top match {top.investigation_id} score={top.similarity_score} root_cause={top.root_cause}"
            )
            correlations.append("historical_investigation_match")
            if top.historical_feedback:
                observations.append(
                    f"Historical feedback available for top match ({len(top.historical_feedback)} item(s))."
                )
        else:
            observations.append("No similar investigations found.")

        confidence = 0.15
        confidence += 0.2 * bool(runbooks)
        confidence += 0.25 * bool(known_issues)
        confidence += 0.2 * bool(similar)

        summary = (
            f"Knowledge analysis surfaced {len(runbooks)} runbook(s), "
            f"{len(known_issues)} known issue(s), and {len(similar)} similar investigation(s)."
        )
        return AgentFinding(
            agent_name=self.name,
            summary=summary,
            key_observations=observations,
            suspicious_items=suspicious,
            correlations=correlations,
            confidence=round(min(0.95, confidence), 4),
            evidence={
                "runbook_count": len(runbooks),
                "known_issue_count": len(known_issues),
                "similar_count": len(similar),
            },
        )
