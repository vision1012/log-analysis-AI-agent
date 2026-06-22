"""Schemas for JIRA ticket ingestion and normalization."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class JiraExtractedHints(BaseModel):
    """Deterministic hints parsed from normalized ticket text."""

    service_names: List[str] = Field(default_factory=list)
    environment_names: List[str] = Field(default_factory=list)
    file_paths: List[str] = Field(default_factory=list)
    error_keywords: List[str] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)


class JiraNormalizedTicket(BaseModel):
    """Backend-friendly normalized JIRA ticket context."""

    ticket_id: Optional[str] = None
    ticket_key: str = "UNKNOWN"
    summary: str = ""
    description: str = ""
    comments_text: str = ""
    status: Optional[str] = "unknown"
    priority: Optional[str] = "unknown"
    labels: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    url: str = ""
    cleaned_text_body: str = ""


class JiraTicketFetchResponse(BaseModel):
    """Response for GET /api/v1/jira/tickets/{ticket_key}."""

    ticket: JiraNormalizedTicket
    hints: JiraExtractedHints


class JiraTicketSearchHit(BaseModel):
    """Lightweight row for ticket search / picker UI."""

    ticket_key: str
    summary: str = ""
    status: Optional[str] = None
    priority: Optional[str] = None
    updated_at: Optional[str] = None
    labels: List[str] = Field(default_factory=list)


class JiraTicketSearchResponse(BaseModel):
    """Response for GET /api/v1/jira/tickets/search."""

    issues: List[JiraTicketSearchHit] = Field(default_factory=list)
    total: int = 0
    jql_used: str = Field(
        "",
        description="Effective JQL sent to JIRA (built from q or taken from jql).",
    )
