"""Tests for human feedback learning service."""

from __future__ import annotations

from typing import Any

import pytest

from feedback.feedback_learning_service import (
    confirm_feedback,
    get_confirmation_rate,
    get_feedback_by_investigation_ids,
    get_feedback_for_investigation,
    get_most_confirmed_candidates,
    get_most_rejected_candidates,
    get_rejection_rate,
    override_feedback,
    record_feedback,
    reject_feedback,
)
from feedback.feedback_models import FeedbackType


class _MockClient:
    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.feedback_rows: list[dict[str, Any]] = []
        self.rate_rows: dict[str, list[dict[str, Any]]] = {}
        self.candidate_rows: dict[str, list[dict[str, Any]]] = {}

    def execute_write(self, query: str, parameters: dict[str, Any] | None = None) -> None:
        self.writes.append((query, parameters or {}))

    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        params = parameters or {}
        if "UNWIND $investigation_ids" in query:
            ids = params.get("investigation_ids") or []
            return [
                {**row, "investigation_id": inv_id}
                for inv_id in ids
                for row in self.feedback_rows
                if row.get("investigation_id") == inv_id
            ]
        if "toFloat(confirmed) / total" in query:
            key = f"confirm:{params.get('investigation_id', 'global')}"
            return self.rate_rows.get(key, [{"rate": 0.0}])
        if "toFloat(rejected) / total" in query:
            key = f"reject:{params.get('investigation_id', 'global')}"
            return self.rate_rows.get(key, [{"rate": 0.0}])
        if "feedback_type: 'CONFIRMED'" in query and "ORDER BY count DESC" in query:
            return self.candidate_rows.get("confirmed", [])
        if "feedback_type: 'REJECTED'" in query and "ORDER BY count DESC" in query:
            return self.candidate_rows.get("rejected", [])
        if "f.investigation_id = $investigation_id" in query:
            inv_id = params.get("investigation_id")
            return [r for r in self.feedback_rows if r.get("investigation_id") == inv_id]
        return []


def test_record_feedback_persists_node_and_relationships() -> None:
    client = _MockClient()
    record = record_feedback(
        client,
        investigation_id="inv-1",
        candidate_id="/srv/auth/handler.py",
        feedback_type=FeedbackType.CONFIRMED,
        user_id="user-1",
        comments="looks correct",
        feedback_id="fb-1",
        created_at="2024-01-01T00:00:00Z",
    )
    assert record.feedback_id == "fb-1"
    assert record.feedback_type == "CONFIRMED"
    assert len(client.writes) == 1
    assert "RCACandidate" in client.writes[0][0]
    assert "HAS_FEEDBACK" in client.writes[0][0]
    assert client.writes[0][1]["candidate_id"] == "/srv/auth/handler.py"


def test_override_feedback_links_override_candidate() -> None:
    client = _MockClient()
    record = override_feedback(
        client,
        investigation_id="inv-1",
        candidate_id="/srv/auth/handler.py",
        override_candidate_id="/srv/auth/service.py",
        user_id="user-1",
    )
    assert record.feedback_type == "OVERRIDDEN"
    assert record.override_candidate_id == "/srv/auth/service.py"
    assert len(client.writes) == 2
    assert "OVERRIDDEN_TO" in client.writes[1][0]


def test_confirm_and_reject_wrappers() -> None:
    client = _MockClient()
    confirmed = confirm_feedback(
        client,
        investigation_id="inv-1",
        candidate_id="c1",
        user_id="u1",
    )
    rejected = reject_feedback(
        client,
        investigation_id="inv-1",
        candidate_id="c2",
        user_id="u1",
    )
    assert confirmed.feedback_type == "CONFIRMED"
    assert rejected.feedback_type == "REJECTED"


def test_get_feedback_for_investigation() -> None:
    client = _MockClient()
    client.feedback_rows = [
        {
            "feedback_id": "fb-1",
            "investigation_id": "inv-1",
            "candidate_id": "c1",
            "feedback_type": "CONFIRMED",
            "comments": "",
            "user_id": "u1",
            "created_at": "2024-01-02T00:00:00Z",
            "override_candidate_id": "",
        },
        {
            "feedback_id": "fb-2",
            "investigation_id": "inv-2",
            "candidate_id": "c2",
            "feedback_type": "REJECTED",
            "comments": "",
            "user_id": "u1",
            "created_at": "2024-01-01T00:00:00Z",
            "override_candidate_id": "",
        },
    ]
    rows = get_feedback_for_investigation(client, "inv-1")
    assert len(rows) == 1
    assert rows[0].feedback_id == "fb-1"


def test_get_feedback_by_investigation_ids_batch() -> None:
    client = _MockClient()
    client.feedback_rows = [
        {
            "feedback_id": "fb-1",
            "investigation_id": "inv-a",
            "candidate_id": "c1",
            "feedback_type": "CONFIRMED",
            "comments": "",
            "user_id": "u1",
            "created_at": "2024-01-01T00:00:00Z",
            "override_candidate_id": "",
        }
    ]
    result = get_feedback_by_investigation_ids(client, ["inv-a", "inv-b"])
    assert len(result["inv-a"]) == 1
    assert result["inv-b"] == []


def test_analytics_rates_and_top_candidates() -> None:
    client = _MockClient()
    client.rate_rows["confirm:global"] = [{"rate": 0.5}]
    client.rate_rows["reject:global"] = [{"rate": 0.25}]
    client.candidate_rows["confirmed"] = [{"candidate_id": "c1", "count": 3}]
    client.candidate_rows["rejected"] = [{"candidate_id": "c2", "count": 2}]

    assert get_confirmation_rate(client) == 0.5
    assert get_rejection_rate(client) == 0.25
    assert get_most_confirmed_candidates(client, limit=5)[0].candidate_id == "c1"
    assert get_most_rejected_candidates(client, limit=5)[0].count == 2


def test_analytics_empty_returns_zero() -> None:
    client = _MockClient()
    assert get_confirmation_rate(client) == 0.0
    assert get_rejection_rate(client) == 0.0
    assert get_most_confirmed_candidates(client) == []
