"""Reusable fail-safe LLM client for RCA explanations."""

from __future__ import annotations

import logging
import os
import requests

logger = logging.getLogger(__name__)

_TEST_MODE_EXPLANATION = (
    "Deterministic RCA identified the root cause. LLM explanation is disabled in test mode."
)
_LLM_FAILURE_FALLBACK = (
    "Deterministic RCA identified the root cause. LLM explanation is currently unavailable."
)


def _is_test_or_ci_mode() -> bool:
    return os.getenv("CI") == "true" or bool(os.getenv("PYTEST_CURRENT_TEST"))


def _is_llm_disabled() -> bool:
    return (os.getenv("DISABLE_LLM") or "").strip().lower() == "true"


def _ollama_base_url() -> str:
    return (os.getenv("OLLAMA_BASE_URL") or "http://host.docker.internal:11434").rstrip("/")


def call_llm(root_cause: str) -> str:
    if _is_test_or_ci_mode() or _is_llm_disabled():
        return _TEST_MODE_EXPLANATION

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
            f"{_ollama_base_url()}/api/generate",
            json={"model": "llama3:latest", "prompt": prompt, "stream": False},
            timeout=15,
        )
        print("LLM RESPONSE:", res.status_code)
        res.raise_for_status()
        out = str(res.json().get("response", "")).strip()
        if out:
            return out
        return _LLM_FAILURE_FALLBACK
    except Exception as e:
        print("LLM ERROR:", str(e))
        logger.exception("llm call failed root_cause=%s error=%s", root_cause, str(e))
        return _LLM_FAILURE_FALLBACK


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
