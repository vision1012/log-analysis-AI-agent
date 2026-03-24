"""Pydantic schemas for job API (Neo4j jobs + PostgreSQL user identity)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateJobRequest(BaseModel):
    """Body for ``POST /jobs``."""

    job_type: str = Field(..., min_length=1, max_length=128)
    anomaly_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    triggered_by_user_id: UUID
    trigger_source: str = Field(..., min_length=1, max_length=256)


class JobUserSummary(BaseModel):
    """Resolved user from PostgreSQL (identity source of truth)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    name: str
    email: str
    role: str
    team: Optional[str] = None


class JobResponse(BaseModel):
    """Job fields from Neo4j."""

    job_id: str
    job_type: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    anomaly_id: Optional[str] = None
    run_id: Optional[str] = None
    triggered_by_user_id: Optional[str] = None
    trigger_source: Optional[str] = None
    error_message: Optional[str] = None


class JobDetailResponse(BaseModel):
    """Single job with resolved user summary."""

    job: JobResponse
    user: Optional[JobUserSummary] = None
