"""
Agent Roles Module

Multi-agent system with specialized roles:
- Retrieval Agent: Finds evidence using RAG
- Investigation Agent: Analyzes sequences and patterns
- Reporter Agent: Writes final answer from findings

Each agent produces structured outputs that feed into the next.
"""

from agent.roles.retrieval_agent import RetrievalAgent
from agent.roles.investigation_agent import InvestigationAgent
from agent.roles.reporter_agent import ReporterAgent

__all__ = [
    "RetrievalAgent",
    "InvestigationAgent",
    "ReporterAgent",
]
