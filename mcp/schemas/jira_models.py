"""Normalized JIRA investigation models (no raw JIRA API payloads)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class McpJiraComment(BaseModel):
    author: str = ""
    body: str = ""
    created_at: Optional[str] = None


class McpLinkedIssue(BaseModel):
    issue_key: str
    link_type: str = ""
    summary: str = ""
    status: Optional[str] = None


class McpTicketContext(BaseModel):
    issue_key: str
    summary: str = ""
    description: str = ""
    status: Optional[str] = None
    priority: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    comments: List[McpJiraComment] = Field(default_factory=list)
    linked_issues: List[McpLinkedIssue] = Field(default_factory=list)
    url: str = ""
