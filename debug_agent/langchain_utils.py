"""Lightweight LangChain helpers for LLM-assisted debug-agent stages."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from graphrag.llm_client import LLMConfig

logger = logging.getLogger(__name__)


def render_prompt(template: str, **variables: Any) -> str:
    """Render a string prompt using LangChain PromptTemplate."""
    try:
        from langchain_core.prompts import PromptTemplate
    except Exception:
        # Keep behavior resilient even if LangChain packages are missing at runtime.
        return template.format(**variables)
    return PromptTemplate.from_template(template).format(**variables)


def parse_structured_output(raw: Any) -> dict[str, Any]:
    """
    Parse model output into a JSON object dict.

    Accepts plain JSON text, markdown code-fenced JSON, or dict input.
    """
    if isinstance(raw, dict):
        return raw

    if not isinstance(raw, str):
        raise ValueError("LLM output must be dict or JSON string")

    text = raw.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        from langchain_core.output_parsers import JsonOutputParser

        parser = JsonOutputParser()
        parsed = parser.parse(text)
    except Exception:
        parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Parsed LLM output must be a JSON object")
    return parsed


def invoke_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    config: Optional[LLMConfig] = None,
) -> dict[str, Any]:
    """
    Invoke LLM via LangChain and return parsed JSON object.

    Current LangChain path supports openai provider. Other providers should use caller fallback.
    """
    cfg = config or LLMConfig.from_env()
    provider = (cfg.provider or "").strip().lower()
    if provider != "openai":
        raise RuntimeError(f"LangChain invocation unsupported for provider: {provider}")

    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:  # pragma: no cover - import-time environment dependent
        raise RuntimeError("langchain-openai package is required for openai provider") from exc
    from langchain_core.messages import HumanMessage, SystemMessage

    model = ChatOpenAI(
        model=cfg.model,
        api_key=cfg.api_key,
        timeout=cfg.timeout_sec,
        temperature=cfg.temperature,
    )
    resp = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    content = resp.content
    if isinstance(content, list):
        content = "\n".join(str(x) for x in content)
    return parse_structured_output(content)


def invoke_with_safe_fallback(
    *,
    primary_call: Callable[[], dict[str, Any]],
    fallback_call: Callable[[], dict[str, Any]],
    context: str = "",
) -> dict[str, Any]:
    """
    Run a primary LLM call and safely fallback on provider/runtime failures.

    This preserves existing agent fallback behavior while enabling LangChain where available.
    """
    try:
        return primary_call()
    except Exception as exc:
        logger.warning("debug_agent.langchain_utils.primary_failed context=%s error=%s", context, str(exc))
        return fallback_call()


def json_payload(payload: dict[str, Any]) -> str:
    """Stable JSON encoding helper for user prompt payloads."""
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str)
