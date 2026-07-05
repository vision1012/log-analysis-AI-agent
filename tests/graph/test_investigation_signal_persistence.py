"""Tests for InvestigationSignal Neo4j persistence."""

from __future__ import annotations

from typing import Any

from graph.investigation_signal_persistence import persist_investigation_v2_signals
from graph.investigation_writer import InvestigationGraphWriter


class _RecordingClient:
    def __init__(self) -> None:
        self.ops: list[tuple[str, dict[str, Any]]] = []

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def execute_write_tx(self, operations: list[tuple[str, dict[str, Any]]]) -> None:
        self.ops.extend(operations)


def test_persist_investigation_v2_signals_writes_has_rca_signal(monkeypatch) -> None:
    client = _RecordingClient()

    def _from_env():
        return client

    monkeypatch.setattr("graph.investigation_signal_persistence.Neo4jClient.from_env", _from_env)
    monkeypatch.setattr(InvestigationGraphWriter, "write_atomic", lambda self, ops: client.ops.extend(ops))

    payload = {
        "mcp_signal_engine_v2": {
            "candidate_path": "/app/handler.py",
            "signals": [
                {
                    "name": "code_churn",
                    "value": 0.8,
                    "weight": 0.03,
                    "contribution": 0.024,
                    "evidence": {"churn_counts": {7: 3}},
                }
            ],
        }
    }
    count = persist_investigation_v2_signals("inv-1", candidate_path="/app/handler.py", contributions_payload=payload)
    assert count == 1
    assert any("InvestigationSignal" in q for q, _ in client.ops)
    assert any("HAS_RCA_SIGNAL" in q for q, _ in client.ops)
