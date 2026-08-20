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
    temperature: float = 0.2
    # Enough headroom for a 180-300 word explanation_summary plus JSON envelope.
    max_tokens: int = 900

    @classmethod
    def from_env(cls) -> "LLMConfig":
        # Explicit GRAPHRAG_LLM_PROVIDER wins; else use Ollama when OLLAMA_HOST is set (local dev).
        raw_provider = os.getenv("GRAPHRAG_LLM_PROVIDER", "").strip().lower()
        if raw_provider:
            provider = raw_provider
        else:
            provider = "ollama" if os.getenv("OLLAMA_HOST", "").strip() else "stub"
        model = os.getenv("GRAPHRAG_LLM_MODEL", os.getenv("OLLAMA_MODEL", "llama3"))
        timeout_raw = os.getenv("GRAPHRAG_LLM_TIMEOUT_SEC", os.getenv("OLLAMA_TIMEOUT_SEC", "30"))
        base_url = os.getenv("GRAPHRAG_LLM_BASE_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        api_key = os.getenv("GRAPHRAG_LLM_API_KEY", os.getenv("OPENAI_API_KEY"))
        temp_raw = os.getenv("GRAPHRAG_LLM_TEMPERATURE", "0.2")
        tokens_raw = os.getenv("GRAPHRAG_LLM_MAX_TOKENS", "900")
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = 30.0
        # Avoid zero/negative timeouts; cap to keep callers from hanging unbounded.
        timeout = max(1.0, min(600.0, timeout))
        try:
            temperature = float(temp_raw)
        except ValueError:
            temperature = 0.2
        # Keep generation consistent: low-temp band only.
        temperature = max(0.1, min(0.3, temperature))
        try:
            max_tokens = int(tokens_raw)
        except ValueError:
            max_tokens = 900
        max_tokens = max(256, min(2048, max_tokens))
        return cls(
            provider=provider,
            model=model,
            timeout_sec=timeout,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def _strip_json_fence(text: str) -> str:
    """Remove optional ``` / ```json fences from model output."""
    t = text.strip()
    if not t.startswith("`"):
        return t
    lines = t.split("\n")
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_json_object(raw: Any) -> dict[str, Any]:
    """Parse provider output into a JSON object."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("LLM response must be dict or JSON string")
    text = _strip_json_fence(raw).strip()
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
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
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

        try:
            top = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama response is not valid JSON: {exc}") from exc
        if not isinstance(top, dict):
            raise RuntimeError("Ollama top-level response must be a JSON object")
        content = ((top.get("message") or {}) or {}).get("content") or ""
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        content = content.strip()
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
            max_tokens=self.config.max_tokens,
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


_SHORT_EXPLANATION_FALLBACK = (
    "Deterministic RCA identified the root cause. LLM explanation is currently unavailable."
)
_TEST_MODE_EXPLANATION = (
    "Deterministic RCA identified the root cause. LLM explanation is disabled in test mode."
)


def _is_test_or_ci_mode() -> bool:
    return os.getenv("CI") == "true" or bool(os.getenv("PYTEST_CURRENT_TEST"))


def _is_llm_disabled() -> bool:
    return (os.getenv("DISABLE_LLM") or "").strip().lower() == "true"


def generate_short_explanation(root_cause: str, *, config: Optional[LLMConfig] = None) -> str:
    """
    Fail-safe short text explanation for Jira RCA UI (assistive only).

    Uses the same provider selection as GraphRAGLLMClient. Never raises.
    """
    if _is_test_or_ci_mode() or _is_llm_disabled():
        return _TEST_MODE_EXPLANATION

    cfg = config or LLMConfig.from_env()
    prompt = (
        f"You are a senior backend engineer writing an assistive RCA explanation.\n\n"
        f"Root cause candidate: {root_cause}\n\n"
        f"Write a clear 4-5 sentence explanation (about 4-5 short lines) that covers:\n"
        f"1) What this file/component likely does in the system\n"
        f"2) How the failure likely surfaces through this candidate\n"
        f"3) What class of defect is plausible (null handling, timeout, bad config, regression, etc.)\n"
        f"4) Why this candidate is a reasonable place to investigate next\n"
        f"5) One caveat that this is assistive only and should be verified against evidence\n\n"
        f"Requirements: plain prose, exactly 4 or 5 sentences, technical but readable, "
        f"no bullet lists, no JSON, no Markdown headings, no invented file names."
    )
    system_prompt = (
        "Respond with plain text only. Write 4-5 complete sentences. No JSON, no bullets."
    )

    try:
        if cfg.provider == "stub":
            return _SHORT_EXPLANATION_FALLBACK
        if cfg.provider == "ollama":
            url = cfg.base_url.rstrip("/") + "/api/generate"
            payload = {
                "model": cfg.model,
                "prompt": prompt,
                "stream": False,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=min(15.0, cfg.timeout_sec)) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            out = str(body.get("response", "")).strip()
            return out or _SHORT_EXPLANATION_FALLBACK
        if cfg.provider == "openai":
            try:
                from openai import OpenAI
            except Exception as exc:
                raise RuntimeError("openai package not installed for openai provider") from exc
            client = OpenAI(api_key=cfg.api_key)
            response = client.chat.completions.create(
                model=cfg.model,
                temperature=cfg.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                timeout=cfg.timeout_sec,
            )
            out = (response.choices[0].message.content or "").strip()
            return out or _SHORT_EXPLANATION_FALLBACK
        return _SHORT_EXPLANATION_FALLBACK
    except Exception as exc:
        logger.exception("graphrag.llm.generate_short_explanation failed root_cause=%s error=%s", root_cause, exc)
        return _SHORT_EXPLANATION_FALLBACK
