"""Base contract for specialized investigation agents."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agents.agent_models import AgentFinding, AgentInvestigationContext


class BaseAgent(ABC):
    """Independent investigator that analyzes one slice of incident context."""

    name: str = "base"

    @abstractmethod
    def investigate(self, context: AgentInvestigationContext) -> AgentFinding:
        """Analyze context and return structured findings."""
