"""
Observability middleware for FastAPI.

Adds request ID tracking and request/response logging.
Uses standard library only (no heavy dependencies).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Configure standard library logging
logger = logging.getLogger("api.middleware")
logger.setLevel(logging.INFO)

# Create console handler if not exists
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request observability.

    Features:
    - Adds X-Request-Id header (generates UUID if missing)
    - Logs request method, path, status code, and latency
    - Excludes health check endpoints from detailed logging
    """

    def __init__(self, app: ASGIApp, exclude_paths: list[str] | None = None):
        """
        Initialize observability middleware.

        Args:
            app: ASGI application.
            exclude_paths: List of path prefixes to exclude from logging (e.g., ["/health"]).
        """
        super().__init__(app)
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/openapi.json", "/redoc"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and add observability.

        Args:
            request: FastAPI request object.
            call_next: Next middleware/handler in chain.

        Returns:
            Response with X-Request-Id header.
        """
        # Get or generate request ID
        request_id = request.headers.get("X-Request-Id")
        if not request_id:
            request_id = str(uuid.uuid4())

        # Add request ID to request state for use in handlers
        request.state.request_id = request_id

        # Check if path should be excluded from logging
        should_log = not any(request.url.path.startswith(path) for path in self.exclude_paths)

        # Start timing
        start_time = time.time()

        # Process request
        try:
            response = await call_next(request)
        except Exception as exc:
            # Log exception
            latency_ms = (time.time() - start_time) * 1000
            logger.error(
                f"Request failed: {request.method} {request.url.path} "
                f"status=500 latency={latency_ms:.2f}ms request_id={request_id} error={exc}"
            )
            raise

        # Calculate latency
        latency_ms = (time.time() - start_time) * 1000

        # Add request ID to response headers
        response.headers["X-Request-Id"] = request_id

        # Log request/response (skip excluded paths)
        if should_log:
            logger.info(
                f"Request: {request.method} {request.url.path} "
                f"status={response.status_code} latency={latency_ms:.2f}ms request_id={request_id}"
            )

        return response
