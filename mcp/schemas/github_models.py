"""Normalized GitHub investigation models."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class McpCommit(BaseModel):
    sha: str
    message: str = ""
    author: str = ""
    committed_at: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)


class McpPullRequest(BaseModel):
    number: int
    title: str = ""
    state: str = ""
    merged: bool = False
    author: str = ""
    created_at: Optional[str] = None
    merged_at: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)
    url: str = ""
