"""Tests for investigation graph visualization service."""

from __future__ import annotations

from typing import Any

import pytest

from graph.graph_visualization_service import (
    _clamp_depth,
    _map_edge_type,
    get_investigation_graph,
    investigation_exists,
)


class _MockClient:
    def __init__(self, *, exists: bool = True, node_rows: list[dict[str, Any]] | None = None, edge_rows: list[dict[str, Any]] | None = None) -> None:
        self.exists = exists
        self.node_rows = node_rows or []
        self.edge_rows = edge_rows or []
        self.queries: list[str] = []

    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.queries.append(query)
        if "RETURN i.id AS id LIMIT 1" in query:
            return [{"id": parameters.get("investigation_id")}] if self.exists else []
        if "properties(n) AS props" in query:
            return self.node_rows
        if "type(r) AS rel_type" in query:
            return self.edge_rows
        return []


def test_clamp_depth_bounds() -> None:
    assert _clamp_depth(None) == 2
    assert _clamp_depth(0) == 1
    assert _clamp_depth(2) == 2
    assert _clamp_depth(9) == 3


def test_map_edge_types_includes_feedback_relationships() -> None:
    assert _map_edge_type("HAS_FEEDBACK") == "HAS_FEEDBACK"
    assert _map_edge_type("TARGETS_CANDIDATE") == "TARGETS_CANDIDATE"
    assert _map_edge_type("TRIGGERED_BUILD") == "TRIGGERED_BUILD"
    assert _map_edge_type("PRODUCED_DEPLOYMENT") == "DEPLOYED_AS"
    assert _map_edge_type("HAS_RUNBOOK") == "HAS_RUNBOOK"
    assert _map_edge_type("UNKNOWN_REL") == "RELATED_TO"


def test_get_investigation_graph_includes_feedback_relationships() -> None:
    client = _MockClient(
        node_rows=[
            {"labels": ["Investigation"], "props": {"id": "inv-1"}},
            {
                "labels": ["Feedback"],
                "props": {
                    "feedback_id": "fb-1",
                    "feedback_type": "CONFIRMED",
                    "comments": "Looks correct",
                },
            },
            {"labels": ["RCACandidate"], "props": {"candidate_id": "cand-1"}},
        ],
        edge_rows=[
            {
                "rel_type": "HAS_FEEDBACK",
                "src_labels": ["Investigation"],
                "src_props": {"id": "inv-1"},
                "tgt_labels": ["Feedback"],
                "tgt_props": {"feedback_id": "fb-1"},
            },
            {
                "rel_type": "TARGETS_CANDIDATE",
                "src_labels": ["Feedback"],
                "src_props": {"feedback_id": "fb-1"},
                "tgt_labels": ["RCACandidate"],
                "tgt_props": {"candidate_id": "cand-1"},
            },
        ],
    )
    result = get_investigation_graph(client, "inv-1", depth=2)
    assert {n["type"] for n in result["nodes"]} == {"Investigation", "Feedback", "RCACandidate"}
    edge_types = {edge["type"] for edge in result["edges"]}
    assert "HAS_FEEDBACK" in edge_types
    assert "TARGETS_CANDIDATE" in edge_types
    assert any(edge["relationship"] == "HAS_FEEDBACK" for edge in result["edges"])
    assert any(edge["relationship"] == "TARGETS_CANDIDATE" for edge in result["edges"])


def test_get_investigation_graph_returns_nodes_and_edges() -> None:
    client = _MockClient(
        node_rows=[
            {"labels": ["Investigation"], "props": {"id": "inv-1", "ticket_key": "OPS-1"}},
            {"labels": ["JiraTicket"], "props": {"issue_key": "OPS-1", "summary": "Auth errors"}},
            {"labels": ["Deployment"], "props": {"id": "dep-1", "environment": "prod"}},
        ],
        edge_rows=[
            {
                "rel_type": "HAS_JIRA_TICKET",
                "src_labels": ["Investigation"],
                "src_props": {"id": "inv-1"},
                "tgt_labels": ["JiraTicket"],
                "tgt_props": {"issue_key": "OPS-1"},
            },
            {
                "rel_type": "PRODUCED_DEPLOYMENT",
                "src_labels": ["Build"],
                "src_props": {"id": "build-1"},
                "tgt_labels": ["Deployment"],
                "tgt_props": {"id": "dep-1"},
            },
        ],
    )
    result = get_investigation_graph(client, "inv-1", depth=2)

    assert len(result["nodes"]) == 3
    assert {n["type"] for n in result["nodes"]} == {"Investigation", "JiraTicket", "Deployment"}
    assert result["edges"]
    assert result["edges"][0]["type"] in {
        "RELATED_TO",
        "DEPLOYED_AS",
        "TRIGGERED_BUILD",
        "PART_OF",
        "CAUSED",
        "TRIGGERED",
        "GENERATED",
        "HAS_RUNBOOK",
        "MATCHES_KNOWN_ISSUE",
        "HAS_FEEDBACK",
        "TARGETS_CANDIDATE",
    }
    assert "[*0..2]" in client.queries[0]


def test_get_investigation_graph_respects_depth_three() -> None:
    client = _MockClient(node_rows=[], edge_rows=[])
    get_investigation_graph(client, "inv-1", depth=3)
    assert "[*0..3]" in client.queries[0]


def test_investigation_exists() -> None:
    assert investigation_exists(_MockClient(exists=True), "inv-1") is True
    assert investigation_exists(_MockClient(exists=False), "inv-1") is False


def test_skips_unsupported_node_labels() -> None:
    client = _MockClient(
        node_rows=[
            {"labels": ["Investigation"], "props": {"id": "inv-1"}},
            {"labels": ["Container"], "props": {"id": "ctr-1", "container_name": "auth"}},
        ],
        edge_rows=[],
    )
    result = get_investigation_graph(client, "inv-1", depth=1)
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["type"] == "Investigation"
