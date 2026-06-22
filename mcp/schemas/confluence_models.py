"""Normalized Confluence knowledge-base models."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RunbookDocument(BaseModel):
    """Service runbook, SOP, or incident response guide."""

    document_id: str = ""
    title: str = ""
    space_key: str = ""
    url: str = ""
    service_name: str = ""
    summary: str = ""
    content_excerpt: str = ""
    labels: List[str] = Field(default_factory=list)
    updated_at: Optional[str] = None


class KnownIssueDocument(BaseModel):
    """Documented known issue with workaround guidance."""

    document_id: str = ""
    title: str = ""
    space_key: str = ""
    url: str = ""
    affected_service: str = ""
    error_keywords: List[str] = Field(default_factory=list)
    workaround: str = ""
    severity: str = ""
    updated_at: Optional[str] = None


class ArchitectureDocument(BaseModel):
    """Architecture or system design documentation."""

    document_id: str = ""
    title: str = ""
    space_key: str = ""
    url: str = ""
    service_name: str = ""
    summary: str = ""
    components: List[str] = Field(default_factory=list)
    updated_at: Optional[str] = None
