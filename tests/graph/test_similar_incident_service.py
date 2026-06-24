"""Tests for similar incident search service."""

from __future__ import annotations

from typing import Any

import pytest

from graph.similar_incident_service import (
    HIGH_LATENCY_MS_THRESHOLD,
    HIGH_METRIC_VALUE_THRESHOLD,
    HIGH_RESTART_COUNT_THRESHOLD,
    KUBERNETES_SIGNAL_KEYS,
    METRIC_SIGNAL_KEYS,
    TRACE_SIGNAL_KEYS,
    _build_match_explanation,
    _compute_kubernetes_similarity_score,
    _compute_metric_similarity_score,
    _compute_trace_similarity_score,
    _compute_architecture_similarity_score,
    _architecture_signal_keys,
    _kubernetes_signal_key,
    _metric_signal_keys,
    _score_shared_keys,
    _trace_signal_keys,
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


def test_score_shared_keys_trace_entities_and_signals() -> None:
    score, factors = _score_shared_keys(
        [
            "TraceEvent:trace-1",
            "TraceSignal:Endpoint:/api/auth",
            "TraceSignal:TraceFailure",
        ],
        root_cause_overlap=False,
    )
    assert "trace_match" in factors
    assert "trace_signal_match" in factors
    assert score > 0
    assert score <= 1.0


@pytest.mark.parametrize(
    ("props", "expected_contains"),
    [
        (
            {
                "endpoint": "/api/auth",
                "service": "auth-service",
                "latency_ms": HIGH_LATENCY_MS_THRESHOLD,
                "error_count": 2,
            },
            [
                "TraceSignal:Endpoint:/api/auth",
                "TraceSignal:Service:auth-service",
                "TraceSignal:HighLatency",
                "TraceSignal:TraceFailure",
                "TraceSignal:ErrorCount",
            ],
        ),
    ],
)
def test_trace_signal_keys_derivation(props: dict[str, Any], expected_contains: list[str]) -> None:
    keys = _trace_signal_keys(props)
    for item in expected_contains:
        assert item in keys
    assert "TraceSignal:HighLatency" in TRACE_SIGNAL_KEYS or "TraceSignal:HighLatency" in keys


def test_compute_trace_similarity_score() -> None:
    score = _compute_trace_similarity_score(
        ["trace_match", "trace_signal_match"],
        ["TraceEvent:trace-1", "TraceSignal:HighLatency"],
    )
    assert score > 0
    assert score <= 1.0


def test_build_match_explanation_trace_failure() -> None:
    explanation = _build_match_explanation(
        ["trace_match", "trace_signal_match"],
        ["TraceEvent:trace-1", "TraceSignal:TraceFailure"],
    )
    assert explanation == "Historical investigation matched due to recurring trace failures"


def test_build_match_explanation_shared_endpoint() -> None:
    explanation = _build_match_explanation(
        ["trace_match", "trace_signal_match"],
        ["TraceEvent:trace-1", "TraceSignal:Endpoint:/api/auth/login"],
    )
    assert explanation == "Shared endpoint /api/auth/login"


def test_build_match_explanation_high_latency_traces() -> None:
    explanation = _build_match_explanation(
        ["trace_match", "trace_signal_match"],
        ["TraceEvent:trace-1", "TraceSignal:HighLatency"],
    )
    assert explanation == "Historical investigation matched due to shared high latency traces"


def test_score_shared_keys_metric_entities_and_signals() -> None:
    score, factors = _score_shared_keys(
        [
            "MetricEvent:metric-1",
            "MetricSignal:Name:error_rate",
            "MetricSignal:MetricSpike",
        ],
        root_cause_overlap=False,
    )
    assert "metric_match" in factors
    assert "metric_signal_match" in factors
    assert score > 0
    assert score <= 1.0


def test_metric_signal_keys_derivation() -> None:
    keys = _metric_signal_keys(
        {
            "metric_name": "http.error_rate",
            "service": "auth-service",
            "severity": "critical",
            "value": HIGH_METRIC_VALUE_THRESHOLD,
        }
    )
    assert "MetricSignal:Name:http.error_rate" in keys
    assert "MetricSignal:Service:auth-service" in keys
    assert "MetricSignal:Severity:critical" in keys
    assert "MetricSignal:MetricSpike" in keys
    assert "MetricSignal:ErrorRate" in keys
    assert "MetricSignal:MetricSpike" in METRIC_SIGNAL_KEYS


def test_metric_signal_keys_includes_latency_metric() -> None:
    keys = _metric_signal_keys({"metric_name": "api.latency.p99", "service": "api"})
    assert "MetricSignal:LatencyMetric" in keys
    assert "MetricSignal:Name:api.latency.p99" in keys


def test_compute_metric_similarity_score() -> None:
    score = _compute_metric_similarity_score(
        ["metric_match", "metric_signal_match"],
        ["MetricEvent:metric-1", "MetricSignal:MetricSpike"],
    )
    assert score > 0
    assert score <= 1.0


def test_build_match_explanation_metric_spike() -> None:
    explanation = _build_match_explanation(
        ["metric_match", "metric_signal_match"],
        ["MetricEvent:metric-1", "MetricSignal:MetricSpike"],
    )
    assert explanation == "Historical investigation matched due to recurring metric spike patterns"


def test_find_similar_investigations_query_includes_metric_entities() -> None:
    client = _MockClient(
        similar_rows=[
            {
                "investigation_id": "inv-old-metric",
                "ticket_key": "OPS-88",
                "created_at": "2024-01-05T10:00:00Z",
                "shared_keys": [
                    "MetricEvent:metric-1",
                    "MetricSignal:Name:http.error_rate",
                    "MetricSignal:MetricSpike",
                ],
            }
        ]
    )
    results = find_similar_investigations(client, "inv-current", limit=5)
    assert len(results) == 1
    assert "metric_match" in results[0].matched_factors
    assert "metric_signal_match" in results[0].matched_factors
    assert results[0].metric_similarity_score > 0
    assert results[0].similarity_score > 0
    assert "metric" in results[0].match_explanation.lower()
    query = next(q for q in client.queries if "shared_keys" in q)
    assert "WHEN 'MetricEvent' THEN 'MetricEvent:' + shared.id" in query
    assert "MetricSignal:Name:" in query
    assert "MetricSignal:Service:" in query
    assert "MetricSignal:Severity:" in query
    assert "MetricSignal:MetricSpike" in query
    assert "MetricSignal:ErrorRate" in query
    assert "MetricSignal:LatencyMetric" in query


def test_find_similar_investigations_query_includes_trace_entities() -> None:
    client = _MockClient(
        similar_rows=[
            {
                "investigation_id": "inv-old-trace",
                "ticket_key": "OPS-99",
                "created_at": "2024-01-04T10:00:00Z",
                "shared_keys": [
                    "TraceEvent:trace-1",
                    "TraceSignal:Endpoint:/api/auth",
                    "TraceSignal:TraceFailure",
                ],
            }
        ]
    )
    results = find_similar_investigations(client, "inv-current", limit=5)
    assert len(results) == 1
    assert "trace_match" in results[0].matched_factors
    assert "trace_signal_match" in results[0].matched_factors
    assert results[0].trace_similarity_score > 0
    assert results[0].similarity_score > 0
    assert "trace" in results[0].match_explanation.lower()
    query = next(q for q in client.queries if "shared_keys" in q)
    assert "WHEN 'TraceEvent' THEN 'TraceEvent:' + shared.id" in query
    assert "TraceSignal:Endpoint:" in query
    assert "TraceSignal:Service:" in query
    assert "TraceSignal:Latency" in query
    assert "TraceSignal:HighLatency" in query
    assert "TraceSignal:ErrorCount" in query
    assert "TraceSignal:TraceFailure" in query


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


def test_compute_architecture_similarity_score() -> None:
    score = _compute_architecture_similarity_score(
        ["architecture_match", "architecture_signal_match"],
        ["ArchitectureDocument:arch-1", "ArchSignal:Subsystem:api-gateway"],
    )
    assert score > 0
    assert score <= 1.0


def test_build_match_explanation_architecture_subsystem() -> None:
    explanation = _build_match_explanation(
        ["architecture_match", "architecture_signal_match"],
        ["ArchitectureDocument:arch-1", "ArchSignal:Subsystem:api-gateway"],
    )
    assert explanation == "Historical investigation matched due to shared architecture subsystem"


def test_architecture_signal_keys_from_props() -> None:
    keys = _architecture_signal_keys(
        {
            "service_name": "auth-service",
            "subsystem": "api-gateway",
            "architecture_pattern": "api-gateway|auth-db",
        }
    )
    assert "ArchSignal:Service:auth-service" in keys
    assert "ArchSignal:Subsystem:api-gateway" in keys
    assert "ArchSignal:Pattern:api-gateway|auth-db" in keys


def test_find_similar_investigations_query_includes_architecture_entities() -> None:
    client = _MockClient(
        similar_rows=[
            {
                "investigation_id": "inv-old-arch",
                "ticket_key": "OPS-99",
                "created_at": "2024-01-05T10:00:00Z",
                "shared_keys": [
                    "ArchitectureDocument:arch-1",
                    "ArchSignal:Subsystem:api-gateway",
                ],
            }
        ]
    )
    results = find_similar_investigations(client, "inv-current", limit=5)
    assert len(results) == 1
    assert "architecture_match" in results[0].matched_factors
    assert "architecture_signal_match" in results[0].matched_factors
    assert results[0].architecture_similarity_score > 0
    assert "shared architecture subsystem" in results[0].match_explanation
    query = next(q for q in client.queries if "shared_keys" in q)
    assert "WHEN 'ArchitectureDocument' THEN 'ArchitectureDocument:' + shared.id" in query
    assert "ArchSignal:Subsystem:" in query
    assert "ArchSignal:Service:" in query
    assert "ArchSignal:Pattern:" in query
