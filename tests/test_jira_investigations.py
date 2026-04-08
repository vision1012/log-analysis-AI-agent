"""Tests for JIRA investigation list/detail retrieval."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.jira_investigation_service import InvestigationNotFoundError, get_investigation


def test_list_investigations_empty_tmp(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_INVESTIGATION_STORE_DIR", str(tmp_path))
    from api.services import jira_investigation_service as mod

    out = mod.list_investigations(limit=10, offset=0)
    assert out.total == 0
    assert out.items == []


def test_list_and_get_investigation_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_INVESTIGATION_STORE_DIR", str(tmp_path))
    from artifacts.investigation_store import LocalFileInvestigationStore

    store = LocalFileInvestigationStore(tmp_path)
    iid = store.create_record(
        {
            "ticket_key": "X-1",
            "ticket_summary": "Hello",
            "anomaly_id": "a1",
            "run_id": "r1",
            "run_status": "completed",
            "relationship_ready_bundle": {"rca_target_file": "/app/x.py"},
            "rca_result_ref": {"evidence_refs": ["e1"], "latest_run_id": "r1"},
        }
    )
    from api.services import jira_investigation_service as mod

    listed = mod.list_investigations(limit=10, offset=0)
    assert listed.total == 1
    assert listed.items[0].investigation_id == iid
    assert listed.items[0].ticket_key == "X-1"
    assert "Candidate file" in listed.items[0].rca_headline

    detail = mod.get_investigation(iid)
    assert detail.ticket_key == "X-1"
    assert detail.relationship_ready_bundle.get("rca_target_file") == "/app/x.py"


def test_get_investigation_not_found(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_INVESTIGATION_STORE_DIR", str(tmp_path))
    with pytest.raises(InvestigationNotFoundError):
        get_investigation("00000000-0000-0000-0000-000000000000")


def test_investigations_routes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_INVESTIGATION_STORE_DIR", str(tmp_path))
    from artifacts.investigation_store import LocalFileInvestigationStore

    store = LocalFileInvestigationStore(tmp_path)
    iid = store.create_record(
        {
            "ticket_key": "P-2",
            "ticket_summary": "Issue",
            "anomaly_id": "a2",
            "run_id": "r2",
            "run_status": "completed",
            "rca_result_ref": {},
        }
    )
    client = TestClient(app)
    r = client.get("/api/v1/jira/investigations")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any(x["investigation_id"] == iid for x in data["items"])

    r2 = client.get(f"/api/v1/jira/investigations/{iid}")
    assert r2.status_code == 200
    assert r2.json()["ticket_key"] == "P-2"

    r404 = client.get("/api/v1/jira/investigations/not-a-real-id")
    assert r404.status_code == 404
    assert r404.json()["detail"]["code"] == "investigation_not_found"
