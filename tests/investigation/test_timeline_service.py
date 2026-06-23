"""Tests for investigation timeline service."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from investigation.timeline_models import InvestigationTimelineEvent
from investigation.timeline_service import build_investigation_timeline


class _MockClient:
    def __init__(
        self,
        *,
        exists: bool = True,
        context_row: dict[str, Any] | None = None,
        graph_nodes: list[dict[str, Any]] | None = None,
        feedback_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.exists = exists
        self.context_row = context_row or {}
        self.graph_nodes = graph_nodes or []
        self.feedback_rows = feedback_rows or []

    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "RETURN i.id AS id LIMIT 1" in query:
            return [{"id": parameters.get("investigation_id")}] if self.exists else []
        if "investigation_created_at" in query and "ticket_props" in query:
            return [self.context_row] if self.context_row else [{"investigation_created_at": "", "ticket_props": None}]
        if "DISTINCT labels(n)" in query or "labels(f) AS labels" in query:
            return self.graph_nodes
        if "f.investigation_id = $investigation_id" in query:
            return self.feedback_rows
        return []


def test_build_timeline_empty_when_investigation_missing() -> None:
    assert build_investigation_timeline(_MockClient(exists=False), "missing") == []


def test_build_timeline_sorts_oldest_to_newest() -> None:
    client = _MockClient(
        context_row={
            "investigation_created_at": "2024-01-01T08:00:00Z",
            "ticket_props": {
                "issue_key": "OPS-1",
                "summary": "Auth outage",
                "status": "Open",
            },
        },
        graph_nodes=[
            {
                "labels": ["AlertEvent"],
                "props": {
                    "id": "alert-1",
                    "title": "Error rate high",
                    "message": "5xx spike",
                    "severity": "high",
                    "service": "auth-service",
                    "triggered_at": "2024-01-01T10:00:00Z",
                },
            },
            {
                "labels": ["Commit"],
                "props": {
                    "sha": "abc123",
                    "message": "Fix auth handler",
                    "committed_at": "2024-01-01T09:00:00Z",
                },
            },
        ],
    )
    events = build_investigation_timeline(client, "inv-1")
    assert len(events) >= 3
    assert events[0].event_type == "JIRA_CREATED"
    assert events[1].event_type == "COMMIT_PUSHED"
    assert events[2].event_type == "ALERT_TRIGGERED"


def test_build_timeline_filters_by_event_type() -> None:
    client = _MockClient(
        graph_nodes=[
            {
                "labels": ["AlertEvent"],
                "props": {
                    "id": "alert-1",
                    "title": "Error rate high",
                    "triggered_at": "2024-01-01T10:00:00Z",
                },
            },
            {
                "labels": ["Pod"],
                "props": {
                    "id": "pod-1",
                    "pod_name": "auth-1",
                    "restart_count": 2,
                    "timestamp": "2024-01-01T11:00:00Z",
                },
            },
        ]
    )
    events = build_investigation_timeline(client, "inv-1", event_type="POD_RESTART")
    assert len(events) == 1
    assert events[0].event_type == "POD_RESTART"
    assert events[0].source == "Kubernetes"


def test_build_timeline_includes_feedback_and_rca(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JIRA_INVESTIGATION_STORE_DIR", str(tmp_path))
    from artifacts.investigation_store import LocalFileInvestigationStore

    store = LocalFileInvestigationStore(tmp_path)
    store.create_record(
        {
            "investigation_id": "inv-1",
            "run_status": "completed",
            "created_at": "2024-01-01T12:00:00Z",
            "ticket_summary": "Auth outage",
            "relationship_ready_bundle": {"rca_target_file": "/srv/auth/handler.py"},
        }
    )

    client = _MockClient(
        feedback_rows=[
            {
                "feedback_id": "fb-1",
                "investigation_id": "inv-1",
                "candidate_id": "/srv/auth/handler.py",
                "feedback_type": "CONFIRMED",
                "comments": "Looks right",
                "user_id": "user-1",
                "created_at": "2024-01-01T13:00:00Z",
                "override_candidate_id": "",
            }
        ]
    )
    events = build_investigation_timeline(client, "inv-1")
    types = [event.event_type for event in events]
    assert "RCA_COMPLETED" in types
    assert "FEEDBACK_SUBMITTED" in types
    assert events[-1].event_type == "FEEDBACK_SUBMITTED"


def test_build_timeline_filters_by_time_window() -> None:
    client = _MockClient(
        graph_nodes=[
            {
                "labels": ["AlertEvent"],
                "props": {
                    "id": "alert-1",
                    "title": "Early alert",
                    "triggered_at": "2024-01-01T09:00:00Z",
                },
            },
            {
                "labels": ["AlertEvent"],
                "props": {
                    "id": "alert-2",
                    "title": "Late alert",
                    "triggered_at": "2024-01-01T12:00:00Z",
                },
            },
        ]
    )
    events = build_investigation_timeline(
        client,
        "inv-1",
        from_ts="2024-01-01T10:00:00Z",
        to_ts="2024-01-01T13:00:00Z",
    )
    assert len(events) == 1
    assert events[0].title == "Late alert"
