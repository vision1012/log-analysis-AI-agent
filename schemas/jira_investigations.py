"""Schemas for JIRA-first RCA investigation history (file-backed store)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JiraInvestigationListItem(BaseModel):
    """One row in investigation history (lightweight)."""

    investigation_id: str
    run_id: str = ""
    ticket_key: str = ""
    ticket_summary: str = ""
    anomaly_id: str = ""
    created_at: Optional[str] = None
    run_status: str = ""
    rca_headline: str = Field(
        "",
        description="Short RCA summary line (no raw logs; derived from stored metadata).",
    )


class JiraInvestigationListResponse(BaseModel):
    """Paginated list of past investigations."""

    items: List[JiraInvestigationListItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class JiraInvestigationDetailResponse(BaseModel):
    """
    Full persisted investigation record.

    Raw uploaded log text is not stored and is never returned here.
    """

    investigation_id: str
    schema_version: str = "1.0.0"
    created_at: Optional[str] = None
    ticket_key: str = ""
    ticket_id: Optional[str] = None
    ticket_summary: str = ""
    ticket_status: Optional[str] = None
    anomaly_id: str = ""
    run_id: str = ""
    run_status: str = ""
    rca_result_ref: Dict[str, Any] = Field(default_factory=dict)
    derived_signals_snapshot: Dict[str, Any] = Field(default_factory=dict)
    future_graph_links: Dict[str, Any] = Field(default_factory=dict)
    relationship_ready_bundle: Dict[str, Any] = Field(
        default_factory=dict,
        description="Graph-ready scaffold; same as persisted JSON.",
    )
