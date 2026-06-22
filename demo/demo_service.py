"""
Conference demo mode service.

Launches pre-built scenarios into investigation store, Neo4j graph, timeline, and feedback
without invoking deterministic RCA or GraphRAG pipelines.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from demo.demo_models import DemoLaunchResult, DemoScenario
from demo.demo_scenarios import all_scenario_bundles, get_scenario_bundle
from feedback.feedback_learning_service import (
    confirm_feedback,
    override_feedback,
    reject_feedback,
)
from feedback.feedback_models import FeedbackType
from graph.investigation_graph_service import InvestigationGraphService, investigation_graph_enabled
from graph.neo4j_client import Neo4jClient
from investigation.timeline_service import build_investigation_timeline
from mcp.context.investigation_context import UnifiedInvestigationContext


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_investigation_store():
    from artifacts.investigation_store import LocalFileInvestigationStore

    base = os.environ.get("JIRA_INVESTIGATION_STORE_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        "jira_rca_investigations",
    )
    return LocalFileInvestigationStore(base)


def list_scenarios() -> list[DemoScenario]:
    """Return all available demo scenarios."""
    return [bundle.scenario for bundle in all_scenario_bundles().values()]


def load_scenario(scenario_id: str) -> DemoScenario:
    """Load one demo scenario by id."""
    return get_scenario_bundle(scenario_id).scenario


def _confidence_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _build_store_record(
    scenario: DemoScenario,
    investigation_id: str,
    *,
    run_id: str,
) -> dict[str, Any]:
    return {
        "investigation_id": investigation_id,
        "ticket_key": scenario.ticket_key,
        "ticket_summary": scenario.title,
        "ticket_status": "In Progress",
        "run_id": run_id,
        "run_status": "completed",
        "created_at": _utc_now_iso(),
        "rca_result_ref": {
            "latest_run_id": run_id,
            "evidence_refs": [f"demo-evidence-{scenario.scenario_id}"],
        },
        "derived_signals_snapshot": {
            "ticket_hints": {
                "service_names": [scenario.service_name],
                "file_paths": [scenario.root_cause],
                "error_keywords": [scenario.severity],
            },
            "log_signals": {
                "severity_counts": {"error": 12, "warn": 4},
                "service_names": [scenario.service_name],
                "file_paths": [scenario.root_cause],
            },
            "merged": {
                "service_names": [scenario.service_name],
                "file_paths": [scenario.root_cause],
            },
        },
        "future_graph_links": {
            "ticket": scenario.ticket_key,
            "services": [scenario.service_name],
            "files": [scenario.root_cause],
        },
        "relationship_ready_bundle": {
            "ticket_key": scenario.ticket_key,
            "rca_target_file": scenario.root_cause,
            "candidate_services": [scenario.service_name],
            "candidate_errors": [scenario.severity],
            "candidate_file_paths": [scenario.root_cause],
            "entity_refs": {
                "ticket": [scenario.ticket_key],
                "service": [scenario.service_name],
                "file": [scenario.root_cause],
            },
        },
        "confidence_assessments": [
            {
                "candidate": scenario.root_cause,
                "confidence": scenario.confidence,
                "confidence_level": _confidence_level(scenario.confidence),
                "supporting_factors": [
                    "deployment_proximity",
                    "alert_correlation",
                    "historical_investigation",
                ],
            }
        ],
        "demo_scenario_id": scenario.scenario_id,
        "resolution_summary": scenario.resolution,
    }


def _seed_feedback(
    client: Neo4jClient,
    *,
    investigation_id: str,
    seed: Any,
    user_id: str,
) -> bool:
    feedback_type = str(seed.feedback_type or "CONFIRMED").upper()
    candidate_id = str(seed.candidate_id or "")
    if not candidate_id:
        return False
    actor = str(user_id or seed.user_id or "demo-engineer")
    comments = str(seed.comments or "")

    if feedback_type == FeedbackType.REJECTED.value:
        reject_feedback(
            client,
            investigation_id=investigation_id,
            candidate_id=candidate_id,
            user_id=actor,
            comments=comments,
        )
    elif feedback_type == FeedbackType.OVERRIDDEN.value:
        override_candidate_id = str(seed.override_candidate_id or "")
        if not override_candidate_id:
            return False
        override_feedback(
            client,
            investigation_id=investigation_id,
            candidate_id=candidate_id,
            override_candidate_id=override_candidate_id,
            user_id=actor,
            comments=comments,
        )
    else:
        confirm_feedback(
            client,
            investigation_id=investigation_id,
            candidate_id=candidate_id,
            user_id=actor,
            comments=comments,
        )
    return True


def _persist_graph(
    investigation_id: str,
    context: UnifiedInvestigationContext,
    *,
    ticket_key: str,
) -> dict[str, int]:
    if not investigation_graph_enabled():
        return {"nodes": 0, "relationships": 0}
    return InvestigationGraphService().persist_investigation_context(
        investigation_id,
        context,
        ticket_key=ticket_key,
    )


def launch_scenario(
    scenario_id: str,
    *,
    user_id: str = "demo-engineer",
    graph_client: Neo4jClient | None = None,
) -> DemoLaunchResult:
    """
    Launch a demo scenario into a full investigation workspace.

    Creates investigation graph nodes, JSON store record (RCA result), timeline data,
    and optional feedback seed without running RCA or GraphRAG.
    """
    bundle = get_scenario_bundle(scenario_id)
    scenario = bundle.scenario
    investigation_id = str(uuid.uuid4())
    run_id = f"demo-{scenario.scenario_id}-{investigation_id[:8]}"
    context = bundle.build_context()

    graph_counts = {"nodes": 0, "relationships": 0}
    try:
        graph_counts = _persist_graph(investigation_id, context, ticket_key=scenario.ticket_key)
    except Exception:
        graph_counts = {"nodes": 0, "relationships": 0}

    store = _get_investigation_store()
    payload = _build_store_record(scenario, investigation_id, run_id=run_id)
    stored_id = store.create_record(payload)
    investigation_id = stored_id

    feedback_seeded = False
    timeline_event_count = 0
    own_client = graph_client is None
    client = graph_client or Neo4jClient.from_env()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        if bundle.feedback_seed:
            try:
                feedback_seeded = _seed_feedback(
                    client,
                    investigation_id=investigation_id,
                    seed=bundle.feedback_seed,
                    user_id=user_id,
                )
            except Exception:
                feedback_seeded = False
        timeline_event_count = len(build_investigation_timeline(client, investigation_id))
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()

    return DemoLaunchResult(
        scenario_id=scenario.scenario_id,
        investigation_id=investigation_id,
        ticket_key=scenario.ticket_key,
        service_name=scenario.service_name,
        root_cause=scenario.root_cause,
        confidence=scenario.confidence,
        resolution=scenario.resolution,
        graph_nodes=int(graph_counts.get("nodes") or 0),
        graph_relationships=int(graph_counts.get("relationships") or 0),
        timeline_event_count=timeline_event_count,
        feedback_seeded=feedback_seeded,
        rca_completed=True,
    )
