"""Normalized GitLab investigation models."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class McpGitLabCommit(BaseModel):
    id: str
    short_id: str = ""
    title: str = ""
    author: str = ""
    committed_at: Optional[str] = None


class McpMergeRequest(BaseModel):
    iid: int
    title: str = ""
    state: str = ""
    author: str = ""
    created_at: Optional[str] = None
    merged_at: Optional[str] = None
    url: str = ""


class McpPipeline(BaseModel):
    id: int
    status: str = ""
    ref: str = ""
    created_at: Optional[str] = None
    finished_at: Optional[str] = None
    url: str = ""


class McpDeploymentEvent(BaseModel):
    environment: str = ""
    status: str = ""
    deployed_at: Optional[str] = None
    commit_sha: str = ""
    url: str = ""
