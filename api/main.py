"""
FastAPI application entry point for Log Analysis AI Agent.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import debug_agent_routes
from api.middleware.observability import ObservabilityMiddleware
from api.routes import jobs as jobs_routes
from api.routers import feedback_routes, health, rca_routes
from dotenv import load_dotenv

load_dotenv()

# Startup: confirm PYTHONPATH and import roots (Docker: ENV PYTHONPATH=/app)
print("[startup] PYTHONPATH env:", os.environ.get("PYTHONPATH"))
print("[startup] sys.path:", sys.path)


app = FastAPI(
    title="Log Analysis AI Agent API",
    description="REST API for graph-based RCA operations",
    version="1.0.0",
)

# Observability middleware (add first to track all requests)
# Adds X-Request-Id header and logs request/response details
app.add_middleware(
    ObservabilityMiddleware,
    exclude_paths=["/health", "/docs", "/openapi.json", "/redoc"],
)

# CORS middleware for web/mobile clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router, tags=["health"])
app.include_router(rca_routes.router, prefix="/api/v1", tags=["rca"])
app.include_router(feedback_routes.router, prefix="/api/v1", tags=["feedback"])
app.include_router(jobs_routes.router, prefix="/api/v1", tags=["jobs"])
app.include_router(debug_agent_routes.router, tags=["debug-agent"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Log Analysis AI Agent API",
        "version": "1.0.0",
        "docs": "/docs",
    }
