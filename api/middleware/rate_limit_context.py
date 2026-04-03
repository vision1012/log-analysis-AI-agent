"""
Parse ``POST /api/v1/jobs`` JSON once to set ``request.state.rate_limit_user_id`` for keying.

Restores the request body so the route can read it normally.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger("api.middleware.rate_limit_context")


class RateLimitContextMiddleware(BaseHTTPMiddleware):
    """Attach ``triggered_by_user_id`` from job create JSON to request state."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "POST" and request.url.path.rstrip("/") == "/api/v1/jobs":
            body = await request.body()
            try:
                data = json.loads(body)
                uid = data.get("triggered_by_user_id")
                if uid is not None and str(uid).strip():
                    request.state.rate_limit_user_id = str(uid).strip()
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                logger.debug("rate_limit_context jobs body parse skipped: %s", exc)

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request._receive = receive  # type: ignore[attr-defined]

        return await call_next(request)
