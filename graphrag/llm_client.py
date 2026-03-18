"""LLM client abstraction for GraphRAG explanations."""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Minimal protocol expected by explanation_generator."""

    def generate(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return parsed JSON-like dict that follows the output contract."""
        raise NotImplementedError


class StubLLMClient:
    """
    Deterministic fallback client for local integration/testing.

    This avoids introducing provider dependencies in the base module.
    """

    def generate(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        _ = (system_prompt, user_prompt)
        return {
            "summary": "Insufficient model integration: returning deterministic stub explanation.",
            "primary_cause_file_id": "",
            "confidence": 0.0,
            "evidence_bullets": ["No external LLM configured; this is a stub response."],
            "limitations": ["Replace StubLLMClient with a real provider-backed client."],
        }
