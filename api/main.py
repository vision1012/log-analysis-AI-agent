"""
FastAPI application entry point for Log Analysis AI Agent.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.llm_provider_status import log_llm_runtime_snapshot
from api.middleware.observability import ObservabilityMiddleware
from api.middleware.rate_limit_context import RateLimitContextMiddleware
from api.rate_limit.config import load_rate_limit_settings
from api.rate_limit.redis_window import set_redis_client
from api.routes import demo_routes
from api.routes import feedback_learning as feedback_learning_routes
from api.routes import investigation_graph as investigation_graph_routes
from api.routes import rca_evaluation as rca_evaluation_routes
from api.routes import jira_investigations as jira_investigations_routes
from api.routes import mcp_routes
from api.routes.jira_rca import router as jira_rca_router
from api.routes import jobs as jobs_routes
from api.routers import auth_routes, feedback_routes, health, jira_routes, rca_routes, users_routes
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("api.main")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _log_cors_startup()
    log_llm_runtime_snapshot()
    settings = load_rate_limit_settings()
    client = None
    if settings.enabled:
        try:
            import redis.asyncio as redis

            # Redis client for ``fastapi_limiter`` + :class:`api.rate_limit.redis_pyrate_adapter.RedisFixedWindowLimiter`
            client = redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
            await client.ping()
            set_redis_client(client)
            logger.info("rate_limit redis connected url=%s", settings.redis_url.split("@")[-1])
        except Exception as exc:
            if settings.fail_open:
                logger.warning("rate_limit redis unavailable (fail_open): %s", exc)
                if client is not None:
                    await client.aclose()
                set_redis_client(None)
            else:
                raise
    try:
        yield
    finally:
        from api.rate_limit.redis_window import get_redis_client

        c = get_redis_client()
        if c is not None:
            await c.aclose()
            set_redis_client(None)


def _cors_allow_origins() -> list[str]:
    """
    Exact ``Access-Control-Allow-Origin`` allowlist for browser clients.

    Default (when ``CORS_ORIGINS`` is unset): ``http://localhost:5173``,
    ``http://127.0.0.1:5173`` (Vite dev; ``localhost`` vs ``127.0.0.1`` are distinct origins).

    Set ``CORS_ORIGINS`` to a comma-separated list to replace defaults (include every dev URL you need).
    Wildcard is not used with ``allow_credentials=True``.
    """
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def _log_cors_startup() -> None:
    """Log allowed CORS origins at startup (no secrets)."""
    origins = _cors_allow_origins()
    logger.info("cors: allow_origins=%s (override with CORS_ORIGINS)", origins)


app = FastAPI(
    title="Log Analysis AI Agent API",
    description="REST API for graph-based RCA operations",
    version="1.0.0",
    lifespan=_lifespan,
)

# Middleware order: last registered is outermost (runs first on incoming requests).
# Put CORSMiddleware last so browsers get preflight (OPTIONS) + CORS headers before other layers.
#
# Observability (inner side of stack, closer to routes)
app.add_middleware(
    ObservabilityMiddleware,
    exclude_paths=["/health", "/docs", "/openapi.json", "/redoc"],
)

# Parse job-create JSON for per-user rate limit keys
app.add_middleware(RateLimitContextMiddleware)

# CORS outermost — local Vite: http://localhost:5173 and http://127.0.0.1:5173 by default; set CORS_ORIGINS to extend
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)

# Register routers
app.include_router(health.router, tags=["health"])
app.include_router(rca_routes.router, prefix="/api/v1", tags=["rca"])
app.include_router(feedback_routes.router, prefix="/api/v1", tags=["feedback"])
app.include_router(feedback_learning_routes.router, prefix="/api/v1", tags=["feedback-learning"])
app.include_router(jobs_routes.router, prefix="/api/v1", tags=["jobs"])
app.include_router(jira_rca_router, prefix="/api/v1", tags=["jira-rca"])
app.include_router(jira_investigations_routes.router, prefix="/api/v1", tags=["jira-investigations"])
app.include_router(investigation_graph_routes.router, prefix="/api/v1", tags=["investigation-graph"])
app.include_router(rca_evaluation_routes.router, prefix="/api/v1", tags=["rca-evaluation"])
app.include_router(users_routes.router, prefix="/api/v1", tags=["users"])
app.include_router(auth_routes.router, prefix="/api/v1", tags=["auth"])
app.include_router(jira_routes.router, prefix="/api/v1", tags=["jira"])
app.include_router(mcp_routes.router, prefix="/api/v1", tags=["mcp"])
app.include_router(demo_routes.router, prefix="/api/v1", tags=["demo"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Log Analysis AI Agent API",
        "version": "1.0.0",
        "docs": "/docs",
    }
