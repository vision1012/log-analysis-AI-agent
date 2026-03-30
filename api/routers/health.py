"""
Health check router.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from api.llm_provider_status import get_llm_runtime_status

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str


@router.get("/health/llm")
async def health_llm() -> dict[str, Any]:
    """
    Assistive LLM / Ollama runtime status (GraphRAG + debug-agent flags).

    Does not invoke RCA. Use to verify the API process sees OLLAMA_HOST and can reach Ollama.
    """
    return get_llm_runtime_status()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns:
        HealthResponse with status "ok" if service is healthy.
    """
    return HealthResponse(status="ok")
