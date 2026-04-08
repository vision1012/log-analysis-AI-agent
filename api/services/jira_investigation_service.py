"""Read-only access to persisted JIRA-first RCA investigation records."""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict

from artifacts.investigation_store import LocalFileInvestigationStore
from schemas.jira_investigations import (
    JiraInvestigationDetailResponse,
    JiraInvestigationListItem,
    JiraInvestigationListResponse,
)


class InvestigationNotFoundError(Exception):
    """No investigation JSON found for the given id."""


def _get_store() -> LocalFileInvestigationStore:
    base = os.environ.get("JIRA_INVESTIGATION_STORE_DIR") or str(
        tempfile.gettempdir() + "/jira_rca_investigations"
    )
    return LocalFileInvestigationStore(base)


def list_investigations(*, limit: int = 50, offset: int = 0) -> JiraInvestigationListResponse:
    store = _get_store()
    rows, total = store.list_records_summary(limit=limit, offset=offset)
    items = [JiraInvestigationListItem.model_validate(r) for r in rows]
    return JiraInvestigationListResponse(items=items, total=total, limit=limit, offset=offset)


def get_investigation(investigation_id: str) -> JiraInvestigationDetailResponse:
    raw_id = (investigation_id or "").strip()
    if not raw_id:
        raise InvestigationNotFoundError("missing investigation id")
    store = _get_store()
    data = store.get_record(raw_id)
    if not data:
        raise InvestigationNotFoundError(f"investigation not found: {raw_id}")
    return _record_to_detail(data)


def _record_to_detail(data: dict[str, Any]) -> JiraInvestigationDetailResponse:
    """Map persisted JSON to API detail shape (no raw logs)."""
    rel = data.get("relationship_ready_bundle")
    rel_dict: Dict[str, Any] = rel if isinstance(rel, dict) else {}

    return JiraInvestigationDetailResponse(
        investigation_id=str(data.get("investigation_id") or ""),
        schema_version=str(data.get("schema_version") or "1.0.0"),
        created_at=_opt_str(data.get("created_at")),
        ticket_key=str(data.get("ticket_key") or ""),
        ticket_id=_opt_str(data.get("ticket_id")),
        ticket_summary=str(data.get("ticket_summary") or ""),
        ticket_status=_opt_str(data.get("ticket_status")),
        anomaly_id=str(data.get("anomaly_id") or ""),
        run_id=str(data.get("run_id") or ""),
        run_status=str(data.get("run_status") or ""),
        rca_result_ref=_as_dict(data.get("rca_result_ref")),
        derived_signals_snapshot=_as_dict(data.get("derived_signals_snapshot")),
        future_graph_links=_as_dict(data.get("future_graph_links")),
        relationship_ready_bundle=rel_dict,
    )


def _opt_str(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _as_dict(v: object) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}
