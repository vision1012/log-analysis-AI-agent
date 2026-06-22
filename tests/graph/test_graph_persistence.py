"""Tests for investigation graph persistence service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from graph.investigation_graph_service import (
    InvestigationGraphService,
    context_is_empty,
    persist_investigation_context_safe,
)
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.jira_models import McpTicketContext


def test_context_is_empty_detects_no_entities() -> None:
    assert context_is_empty(UnifiedInvestigationContext()) is True
    assert (
        context_is_empty(
            UnifiedInvestigationContext(
                ticket_context=McpTicketContext(issue_key="OPS-1", summary="test")
            )
        )
        is False
    )


@patch("graph.investigation_graph_service.InvestigationGraphService.persist_investigation_context")
def test_persist_investigation_context_safe_returns_true_on_success(mock_persist, monkeypatch) -> None:
    monkeypatch.setenv("INVESTIGATION_GRAPH_ENABLED", "true")
    mock_persist.return_value = {"nodes": 3, "relationships": 2}
    context = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(issue_key="OPS-1", summary="test")
    )
    ok = persist_investigation_context_safe("inv-1", context, ticket_key="OPS-1")
    assert ok is True
    mock_persist.assert_called_once()


@patch("graph.investigation_graph_service.InvestigationGraphService.persist_investigation_context")
def test_persist_investigation_context_safe_swallows_errors(mock_persist, monkeypatch) -> None:
    monkeypatch.setenv("INVESTIGATION_GRAPH_ENABLED", "true")
    mock_persist.side_effect = RuntimeError("neo4j down")
    context = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(issue_key="OPS-1", summary="test")
    )
    ok = persist_investigation_context_safe("inv-1", context, ticket_key="OPS-1")
    assert ok is False


def test_persist_investigation_context_safe_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("INVESTIGATION_GRAPH_ENABLED", "false")
    context = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(issue_key="OPS-1", summary="test")
    )
    ok = persist_investigation_context_safe("inv-1", context)
    assert ok is False


@patch("graph.investigation_graph_service.Neo4jClient")
def test_investigation_graph_service_delegates_to_writer(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client_cls.from_env.return_value = mock_client
    context = UnifiedInvestigationContext(
        ticket_context=McpTicketContext(issue_key="OPS-1", summary="test")
    )

    with patch("graph.investigation_graph_service.InvestigationGraphWriter") as mock_writer_cls:
        mock_writer = mock_writer_cls.return_value
        mock_writer.write_investigation_context.return_value = {"nodes": 1, "relationships": 1}
        counts = InvestigationGraphService().persist_investigation_context("inv-3", context)

    assert counts == {"nodes": 1, "relationships": 1}
    mock_client.connect.assert_called_once()
    mock_client.close.assert_called_once()
    mock_writer.write_investigation_context.assert_called_once_with("inv-3", context, ticket_key="OPS-1")
