"""
FastAPI application entry point for Log Analysis AI Agent.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import debug_agent_routes
from api.llm_provider_status import log_llm_runtime_snapshot
from api.middleware.observability import ObservabilityMiddleware
from api.routes import jobs as jobs_routes
from api.routers import feedback_routes, health, rca_routes, users_routes
from dotenv import load_dotenv

load_dotenv()

# Startup: confirm PYTHONPATH and import roots (Docker: ENV PYTHONPATH=/app)
print("[startup] PYTHONPATH env:", os.environ.get("PYTHONPATH"))
print("[startup] sys.path:", sys.path)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    log_llm_runtime_snapshot()
    yield


def _cors_allow_origins() -> list[str]:
    """
    Origins allowed for browser clients (e.g. Vite on :5173).
    Wildcard is not used with allow_credentials=True (browser CORS rules).
    Override with comma-separated CORS_ORIGINS for deployment or extra dev ports.
    """
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


app = FastAPI(
    title="Log Analysis AI Agent API",
    description="REST API for graph-based RCA operations",
    version="1.0.0",
    lifespan=_lifespan,
)

# Observability middleware (add first to track all requests)
# Adds X-Request-Id header and logs request/response details
app.add_middleware(
    ObservabilityMiddleware,
    exclude_paths=["/health", "/docs", "/openapi.json", "/redoc"],
)

# CORS for separate frontend (Vite default :5173); set CORS_ORIGINS for more origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router, tags=["health"])
app.include_router(rca_routes.router, prefix="/api/v1", tags=["rca"])
app.include_router(feedback_routes.router, prefix="/api/v1", tags=["feedback"])
app.include_router(jobs_routes.router, prefix="/api/v1", tags=["jobs"])
app.include_router(users_routes.router, prefix="/api/v1", tags=["users"])
app.include_router(debug_agent_routes.router, tags=["debug-agent"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Log Analysis AI Agent API",
        "version": "1.0.0",
        "docs": "/docs",
    }
