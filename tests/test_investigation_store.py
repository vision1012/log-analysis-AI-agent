"""Tests for lightweight investigation trace persistence."""

from __future__ import annotations

from artifacts.investigation_store import LocalFileInvestigationStore


def test_local_file_investigation_store_roundtrip(tmp_path) -> None:
    store = LocalFileInvestigationStore(tmp_path)
    record_id = store.create_record(
        {
            "ticket_key": "PROJ-1",
            "ticket_summary": "sample issue",
            "anomaly_id": "an-1",
            "run_id": "run-1",
            "run_status": "completed",
            "derived_signals_snapshot": {"log_signals": {"severity_counts": {"error": 2}}},
            "rca_result_ref": {"latest_run_id": "run-1", "evidence_refs": ["b1"]},
        }
    )
    out = store.get_record(record_id)
    assert out is not None
    assert out["ticket_key"] == "PROJ-1"
    assert out["run_id"] == "run-1"
