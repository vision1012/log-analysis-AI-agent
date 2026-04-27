"""Reusable fail-safe LLM client for RCA explanations."""

from __future__ import annotations

import logging
import requests

logger = logging.getLogger(__name__)


def call_llm(root_cause: str) -> str:
    prompt = f"""
You are a senior backend engineer.

Root cause file: {root_cause}

Write a short 3-4 line explanation describing:
- What this file likely does
- Why it caused the failure
- What kind of bug might exist here

Keep it concise and technical.
Max 4 lines.
No long paragraphs.
No fluff.
Do not mention logs or signals.
"""

    try:
        res = requests.post(
            "http://host.docker.internal:11434/api/generate",
            json={"model": "llama3:latest", "prompt": prompt, "stream": False},
            timeout=15,
        )
        print("LLM RESPONSE:", res.status_code)
        res.raise_for_status()
        out = str(res.json().get("response", "")).strip()
        if out:
            return out
        return (
            f"Issue likely originates from {root_cause}, where incorrect logic or validation "
            "failure is causing the observed error."
        )
    except Exception as e:
        print("LLM ERROR:", str(e))
        logger.exception("llm call failed root_cause=%s error=%s", root_cause, str(e))
        return (
            f"Issue likely originates from {root_cause}, where incorrect logic or validation "
            "failure is causing the observed error."
        )


def generate_explanation(root_cause: str) -> str:
    """
    Backward-compatible wrapper that never raises.
    """
    text = call_llm(root_cause)
    if not text:
        return "LLM explanation unavailable; showing deterministic RCA result."
    if text.lower().startswith("llm failed:"):
        return "LLM explanation unavailable; showing deterministic RCA result."
    return text
