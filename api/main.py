"""
FastAPI application entry point for Log Analysis AI Agent.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.observability import ObservabilityMiddleware
from api.routers import health, jobs

app = FastAPI(
    title="Log Analysis AI Agent API",
    description="REST API for submitting and querying log analysis jobs",
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
app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Log Analysis AI Agent API",
        "version": "1.0.0",
        "docs": "/docs",
    }
