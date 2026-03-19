"""Minimal, swappable LLM client wrapper for GraphRAG explanations."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Minimal interface expected by the explanation layer."""

    def generate(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return parsed JSON-like dict that follows the explanation contract."""
        raise NotImplementedError


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for GraphRAG LLM wrapper."""

    provider: str = "stub"  # stub | ollama | openai
    model: str = "llama3"
    timeout_sec: float = 30.0
    base_url: str = "http://localhost:11434"  # used by ollama
    api_key: Optional[str] = None  # used by openai
    temperature: float = 0.1

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = os.getenv("GRAPHRAG_LLM_PROVIDER", "stub").strip().lower()
        model = os.getenv("GRAPHRAG_LLM_MODEL", os.getenv("OLLAMA_MODEL", "llama3"))
        timeout_raw = os.getenv("GRAPHRAG_LLM_TIMEOUT_SEC", os.getenv("OLLAMA_TIMEOUT_SEC", "30"))
        base_url = os.getenv("GRAPHRAG_LLM_BASE_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        api_key = os.getenv("GRAPHRAG_LLM_API_KEY", os.getenv("OPENAI_API_KEY"))
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = 30.0
        return cls(
            provider=provider,
            model=model,
            timeout_sec=timeout,
            base_url=base_url,
            api_key=api_key,
        )


def _parse_json_object(raw: Any) -> dict[str, Any]:
    """Parse provider output into a JSON object."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("LLM response must be dict or JSON string")
    text = raw.strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


def _fallback_output(reason: str) -> dict[str, Any]:
    return {
        "anomaly_id": "",
        "primary_candidate": {
            "rank": 1,
            "file_id": "",
            "path": "",
            "confidence": 0.0,
            "evidence_ref": "",
        },
        "ranked_hypotheses": [],
        "explanation_summary": "LLM response unavailable; returning safe fallback output.",
        "evidence_highlights": ["No provider response could be validated."],
        "confidence_alignment_note": "Deterministic ranking remains source of truth.",
        "optional_patch_direction": "",
        "limitations": reason,
    }


class GraphRAGLLMClient:
    """Provider-agnostic wrapper with a simple generate() method."""

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig.from_env()

    def generate(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        start = time.monotonic()
        provider = self.config.provider
        model = self.config.model
        logger.info(
            "graphrag.llm.generate.start provider=%s model=%s timeout_sec=%s",
            provider,
            model,
            self.config.timeout_sec,
        )
        try:
            if provider == "stub":
                out = self._generate_stub()
            elif provider == "ollama":
                out = self._generate_ollama(system_prompt=system_prompt, user_prompt=user_prompt)
            elif provider == "openai":
                out = self._generate_openai(system_prompt=system_prompt, user_prompt=user_prompt)
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            parsed = _parse_json_object(out)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "graphrag.llm.generate.success provider=%s model=%s elapsed_ms=%s",
                provider,
                model,
                elapsed_ms,
            )
            return parsed
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "graphrag.llm.generate.failure provider=%s model=%s elapsed_ms=%s error=%s",
                provider,
                model,
                elapsed_ms,
                str(exc),
            )
            return _fallback_output(f"Provider failure: {exc}")

    def _generate_stub(self) -> dict[str, Any]:
        return _fallback_output("Stub provider configured; replace with ollama/openai for live generation.")

    def _generate_ollama(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/api/chat"
        payload = {
            "model": self.config.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": self.config.temperature},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        top = json.loads(body)
        content = ((top.get("message") or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("Ollama response missing message.content")
        return _parse_json_object(content)

    def _generate_openai(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except Exception as exc:
            raise RuntimeError("openai package not installed for openai provider") from exc

        client = OpenAI(api_key=self.config.api_key)
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=self.config.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=self.config.timeout_sec,
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            raise RuntimeError("OpenAI response missing message content")
        return _parse_json_object(content)


class StubLLMClient(GraphRAGLLMClient):
    """Backward-compatible deterministic stub client."""

    def __init__(self) -> None:
        super().__init__(LLMConfig(provider="stub"))
