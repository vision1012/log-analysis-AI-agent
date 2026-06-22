"""Coordinate specialized investigation agents and merge findings."""

from __future__ import annotations

from typing import Iterable, Sequence

from agents.agent_models import AgentFinding, AgentInvestigationContext, MultiAgentInvestigationReport
from agents.base_agent import BaseAgent
from agents.deployment_agent import DeploymentAgent
from agents.incident_agent import IncidentAgent
from agents.infrastructure_agent import InfrastructureAgent
from agents.investigation_context_loader import load_agent_investigation_context
from agents.knowledge_agent import KnowledgeAgent
from agents.rca_agent import RCAAgent
from agents.timeline_agent import TimelineAgent
from graph.neo4j_client import Neo4jClient


def default_agents() -> list[BaseAgent]:
    """Return the standard set of specialized investigation agents."""
    return [
        TimelineAgent(),
        DeploymentAgent(),
        InfrastructureAgent(),
        IncidentAgent(),
        KnowledgeAgent(),
        RCAAgent(),
    ]


def _generate_final_summary(findings: Sequence[AgentFinding]) -> str:
    if not findings:
        return "No agent findings were produced."

    ranked = sorted(findings, key=lambda finding: finding.confidence, reverse=True)
    lead = ranked[0]
    parts = [f"Lead signal from {lead.agent_name} agent (confidence {lead.confidence:.2f}): {lead.summary}"]

    cross_cutting: list[str] = []
    for finding in findings:
        cross_cutting.extend(finding.suspicious_items[:2])
    if cross_cutting:
        unique = list(dict.fromkeys(cross_cutting))[:4]
        parts.append("Key concerns: " + "; ".join(unique))

    correlation_set = []
    for finding in findings:
        correlation_set.extend(finding.correlations[:2])
    if correlation_set:
        unique_corr = list(dict.fromkeys(correlation_set))[:6]
        parts.append("Correlations: " + ", ".join(unique_corr))

    return " ".join(parts)


def run_agents(
    context: AgentInvestigationContext,
    agents: Iterable[BaseAgent] | None = None,
) -> dict[str, AgentFinding]:
    """Run each agent independently against the same read-only context."""
    findings: dict[str, AgentFinding] = {}
    for agent in agents or default_agents():
        findings[agent.name] = agent.investigate(context)
    return findings


def build_multi_agent_report(
    context: AgentInvestigationContext,
    findings: dict[str, AgentFinding],
) -> MultiAgentInvestigationReport:
    """Merge independent agent findings into a unified report."""
    ordered = list(findings.values())
    return MultiAgentInvestigationReport(
        investigation_id=context.investigation_id,
        timeline_findings=findings.get("timeline", AgentFinding(agent_name="timeline", summary="No findings.")),
        deployment_findings=findings.get("deployment", AgentFinding(agent_name="deployment", summary="No findings.")),
        infrastructure_findings=findings.get(
            "infrastructure", AgentFinding(agent_name="infrastructure", summary="No findings.")
        ),
        incident_findings=findings.get("incident", AgentFinding(agent_name="incident", summary="No findings.")),
        knowledge_findings=findings.get("knowledge", AgentFinding(agent_name="knowledge", summary="No findings.")),
        rca_findings=findings.get("rca", AgentFinding(agent_name="rca", summary="No findings.")),
        final_summary=_generate_final_summary(ordered),
    )


def run_multi_agent_investigation(
    client: Neo4jClient,
    investigation_id: str,
    *,
    agents: Iterable[BaseAgent] | None = None,
) -> MultiAgentInvestigationReport:
    """Load context, run all agents independently, and return merged report."""
    context = load_agent_investigation_context(client, investigation_id)
    findings = run_agents(context, agents=agents)
    return build_multi_agent_report(context, findings)
