"""Pydantic schemas for anomaly listing API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AnomalyResponse(BaseModel):
    """Single anomaly record sourced from Neo4j."""

    id: str
    timestamp: datetime | None = None
    trace_ref: str | None = None
    service_ref: str | None = None
    score: float | None = None
    severity: str | None = None
    message: str | None = None
