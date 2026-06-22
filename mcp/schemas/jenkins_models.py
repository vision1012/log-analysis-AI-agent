"""Normalized Jenkins build and deployment models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class BuildEvent(BaseModel):
    """Normalized CI build from Jenkins."""

    build_id: str = ""
    build_number: int = 0
    build_url: str = ""
    status: str = ""
    branch: str = ""
    commit_sha: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    triggered_by: str = ""


class DeploymentEvent(BaseModel):
    """Normalized deployment event (Jenkins or derived from build metadata)."""

    deployment_id: str = ""
    environment: str = ""
    status: str = ""
    commit_sha: str = ""
    build_number: Optional[int] = None
    deployed_at: Optional[str] = None
    deployment_url: str = ""
