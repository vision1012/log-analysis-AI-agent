"""
Runtime snapshot of assistive LLM / Ollama configuration (GraphRAG + debug agents).

Used for startup logs and GET /health/llm. Does not change deterministic RCA.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from graphrag.llm_client import LLMConfig

logger = logging.getLogger(__name__)


def _env_flag_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def _remediation_llm_enabled() -> bool:
    if os.getenv("REMEDIATION_USE_OLLAMA", "").strip().lower() in {"0", "false", "no"}:
        return False
    if os.getenv("REMEDIATION_USE_OLLAMA", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if _env_flag_true("DEBUG_AGENT_REMEDIATION_USE_LLM"):
        return True
    return bool(os.getenv("OLLAMA_HOST", "").strip())


def _reporting_llm_enabled() -> bool:
    if os.getenv("REPORTING_USE_OLLAMA", "").strip().lower() in {"0", "false", "no"}:
        return False
    if os.getenv("REPORTING_USE_OLLAMA", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if _env_flag_true("DEBUG_AGENT_REPORTING_USE_LLM"):
        return True
    return bool(os.getenv("OLLAMA_HOST", "").strip())


def probe_ollama_http(base_url: str, *, timeout_sec: float = 2.0) -> tuple[bool, str | None]:
    """GET /api/tags — lightweight reachability check (no model load)."""
    url = base_url.rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read()
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            try:
                data = json.loads(body.decode("utf-8"))
                models = data.get("models") if isinstance(data, dict) else None
                n = len(models) if isinstance(models, list) else 0
                return True, f"ok models_count={n}"
            except Exception:
                return True, "ok"
    except urllib.error.HTTPError as exc:
        return False, f"HTTPError {exc.code}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason or exc)
    except Exception as exc:
        return False, str(exc)


def get_llm_runtime_status() -> dict[str, Any]:
    """
    Effective GraphRAG LLM config + reachability + assistive agent flags.

    graphrag_effective_provider: stub | ollama | openai — what GraphRAGLLMClient uses.
    """
    cfg = LLMConfig.from_env()
    reachable: bool | None = None
    probe_detail: str | None = None
    if cfg.provider == "ollama":
        reachable, probe_detail = probe_ollama_http(cfg.base_url, timeout_sec=min(3.0, cfg.timeout_sec))
    else:
        probe_detail = "skipped_not_ollama_provider"

    assistive_live_expected = (
        cfg.provider == "ollama"
        and reachable is True
    )

    return {
        "graphrag_effective_provider": cfg.provider,
        "graphrag_llm_model": cfg.model,
        "ollama_base_url": cfg.base_url,
        "ollama_reachable": reachable,
        "ollama_probe_detail": probe_detail,
        "assistive": {
            "explanation_graphrag_uses_ollama": cfg.provider == "ollama",
            "explanation_optional_refinement_llm": _env_flag_true("DEBUG_AGENT_EXPLANATION_USE_LLM"),
            "remediation_llm_intent": _remediation_llm_enabled(),
            "reporting_llm_intent": _reporting_llm_enabled(),
            "assistive_live_expected": assistive_live_expected,
        },
        "env": {
            "OLLAMA_HOST_set": bool(os.getenv("OLLAMA_HOST", "").strip()),
            "GRAPHRAG_LLM_PROVIDER": os.getenv("GRAPHRAG_LLM_PROVIDER", "") or None,
            "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL", "") or None,
        },
    }


def log_llm_runtime_snapshot() -> None:
    """Concise startup log line for ops (easy to grep / remove later)."""
    st = get_llm_runtime_status()
    prov = st["graphrag_effective_provider"]
    reachable = st["ollama_reachable"]
    model = st["graphrag_llm_model"]
    base = st["ollama_base_url"]
    mode = "live" if prov == "ollama" and reachable else ("stub" if prov == "stub" else "fallback_or_unreachable")
    logger.info(
        "api.llm_runtime provider=%s model=%s base_url=%s ollama_reachable=%s mode=%s",
        prov,
        model,
        base,
        reachable,
        mode,
    )
