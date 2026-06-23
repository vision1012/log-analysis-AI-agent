"""Tests for similar incident search service."""

from __future__ import annotations

from typing import Any

import pytest

from graph.similar_incident_service import (
    HIGH_RESTART_COUNT_THRESHOLD,
    KUBERNETES_SIGNAL_KEYS,
    _build_match_explanation,
    _compute_kubernetes_similarity_score,
    _kubernetes_signal_key,
    _score_shared_keys,
    find_similar_investigations,
)


class _MockClient:
    def __init__(
        self,
        *,
        exists: bool = True,
        similar_rows: list[dict[str, Any]] | None = None,
        feedback_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.exists = exists
        self.similar_rows = similar_rows or []
        self.feedback_rows = feedback_rows or []
        self.queries: list[str] = []

    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.queries.append(query)
        if "RETURN i.id AS id LIMIT 1" in query:
            return [{"id": parameters.get("investigation_id")}] if self.exists else []
        if "shared_keys" in query:
            return self.similar_rows
        if "UNWIND $investigation_ids" in query:
            return self.feedback_rows
        return []


def test_score_shared_keys_weighted_factors() -> None:
    score, factors = _score_shared_keys(
        [
            "Service:auth-service",
            "Deployment:dep-1",
            "AlertEvent:alert-1",
            "KnownIssue:ki-1",
        ],
        root_cause_overlap=False,
    )
    assert score > 0
    assert "service_match" in factors
    assert "deployment_match" in factors
    assert "alert_match" in factors
    assert "known_issue_match" in factors
    assert score <= 1.0


def test_score_includes_root_cause_overlap() -> None:
    _, factors = _score_shared_keys([], root_cause_overlap=True)
    assert "root_cause_match" in factors


def test_score_shared_keys_kubernetes_entities_and_signals() -> None:
    score, factors = _score_shared_keys(
        [
            "Pod:pod-auth-1",
            "Container:container-auth-1",
            "Node:node-1",
            "K8sSignal:CrashLoopBackOff",
            "K8sSignal:OOMKilled",
        ],
        root_cause_overlap=False,
    )
    assert "pod_match" in factors
    assert "container_match" in factors
    assert "node_match" in factors
    assert "kubernetes_signal_match" in factors
    assert score > 0
    assert score <= 1.0


@pytest.mark.parametrize(
    ("label", "props", "expected"),
    [
        ("Pod", {"reason": "CrashLoopBackOff"}, "K8sSignal:CrashLoopBackOff"),
        ("Pod", {"reason": "OOMKilled"}, "K8sSignal:OOMKilled"),
        ("Pod", {"reason": "FailedScheduling"}, "K8sSignal:FailedScheduling"),
        ("Pod", {"reason": "ImagePullBackOff"}, "K8sSignal:ImagePullFailure"),
        (
            "Pod",
            {"restart_count": HIGH_RESTART_COUNT_THRESHOLD},
            "K8sSignal:HighRestartCount",
        ),
        ("Pod", {"restart_count": 1}, "K8sSignal:ContainerRestart"),
        ("Container", {"reason": "OOMKilled"}, "K8sSignal:OOMKilled"),
        ("Container", {"reason": "Error", "status": "Terminated"}, "K8sSignal:ContainerFailure"),
        ("Node", {"status": "MemoryPressure"}, "K8sSignal:NodeMemoryPressure"),
        ("Node", {"status": "DiskPressure"}, "K8sSignal:NodeDiskPressure"),
        ("Node", {"status": "PIDPressure"}, "K8sSignal:NodePressure"),
    ],
)
def test_kubernetes_signal_key_derivation(label: str, props: dict[str, Any], expected: str) -> None:
    assert _kubernetes_signal_key(label, props) == expected
    assert expected in KUBERNETES_SIGNAL_KEYS


def test_compute_kubernetes_similarity_score() -> None:
    score = _compute_kubernetes_similarity_score(
        ["pod_match", "kubernetes_signal_match"],
        ["Pod:pod-1", "K8sSignal:OOMKilled"],
    )
    assert score > 0
    assert score <= 1.0


def test_build_match_explanation_oom_killed() -> None:
    explanation = _build_match_explanation(
        ["pod_match", "kubernetes_signal_match"],
        ["Pod:pod-1", "K8sSignal:OOMKilled"],
    )
    assert explanation == "Historical investigation matched due to recurring Kubernetes OOMKilled events"


def test_find_similar_investigations_query_includes_kubernetes_entities() -> None:
    client = _MockClient(
        similar_rows=[
            {
                "investigation_id": "inv-old-k8s",
                "ticket_key": "OPS-42",
                "created_at": "2024-01-03T10:00:00Z",
                "shared_keys": ["Pod:pod-1", "K8sSignal:OOMKilled"],
            }
        ]
    )
    results = find_similar_investigations(client, "inv-current", limit=5)
    assert len(results) == 1
    assert "pod_match" in results[0].matched_factors
    assert "kubernetes_signal_match" in results[0].matched_factors
    assert results[0].kubernetes_similarity_score > 0
    assert "OOMKilled" in results[0].match_explanation
    query = next(q for q in client.queries if "shared_keys" in q)
    assert "WHEN 'Pod' THEN 'Pod:' + shared.id" in query
    assert "K8sSignal:CrashLoopBackOff" in query
    assert "K8sSignal:OOMKilled" in query
    assert "K8sSignal:HighRestartCount" in query
    assert "K8sSignal:ContainerRestart" in query
    assert "K8sSignal:ImagePullFailure" in query
    assert "K8sSignal:FailedScheduling" in query
    assert "K8sSignal:NodeMemoryPressure" in query
    assert "K8sSignal:NodeDiskPressure" in query
    assert "K8sSignal:NodePressure" in query
    assert "K8sSignal:ContainerFailure" in query


def test_find_similar_investigations_returns_ranked_results(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JIRA_INVESTIGATION_STORE_DIR", str(tmp_path))
    client = _MockClient(
        similar_rows=[
            {
                "investigation_id": "inv-old-1",
                "ticket_key": "OPS-10",
                "created_at": "2024-01-01T10:00:00Z",
                "shared_keys": [
                    "Service:auth-service",
                    "Deployment:dep-1",
                    "AlertEvent:alert-1",
                ],
            },
            {
                "investigation_id": "inv-old-2",
                "ticket_key": "OPS-11",
                "created_at": "2024-01-02T10:00:00Z",
                "shared_keys": [],
            },
        ]
    )
    results = find_similar_investigations(client, "inv-current", limit=5)
    assert len(results) == 1
    assert results[0].investigation_id == "inv-old-1"
    assert results[0].similarity_score > 0
    assert results[0].matched_factors
    assert any("[*1..10]" in q for q in client.queries)


def test_find_similar_investigations_empty_when_source_missing() -> None:
    client = _MockClient(exists=False)
    assert find_similar_investigations(client, "missing") == []


def test_find_similar_investigations_includes_historical_feedback(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JIRA_INVESTIGATION_STORE_DIR", str(tmp_path))
    client = _MockClient(
        similar_rows=[
            {
                "investigation_id": "inv-old-1",
                "ticket_key": "OPS-10",
                "created_at": "2024-01-01T10:00:00Z",
                "shared_keys": ["Service:auth-service"],
            },
        ],
        feedback_rows=[
            {
                "investigation_id": "inv-old-1",
                "feedback_id": "fb-1",
                "candidate_id": "/srv/auth/handler.py",
                "feedback_type": "CONFIRMED",
                "comments": "correct",
                "user_id": "user-1",
                "created_at": "2024-01-02T00:00:00Z",
                "override_candidate_id": "",
            }
        ],
    )
    results = find_similar_investigations(client, "inv-current", limit=5)
    assert len(results) == 1
    assert len(results[0].historical_feedback) == 1
    assert results[0].historical_feedback[0].feedback_type == "CONFIRMED"
