"""API layer for human feedback learning (Neo4j persistence)."""

from __future__ import annotations

from feedback.feedback_learning_service import (
    confirm_feedback,
    get_feedback_for_investigation,
    override_feedback,
    reject_feedback,
)
from feedback.feedback_models import FeedbackRecord
from graph.neo4j_client import Neo4jClient


def _get_client() -> Neo4jClient:
    return Neo4jClient.from_env()


def _with_client(fn, *args, **kwargs) -> FeedbackRecord | list[FeedbackRecord]:
    client = _get_client()
    own_client = True
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        return fn(client, *args, **kwargs)
    finally:
        if own_client and getattr(client, "_driver", None):
            client.close()


def submit_confirm_feedback(
    *,
    investigation_id: str,
    candidate_id: str,
    user_id: str,
    comments: str = "",
) -> FeedbackRecord:
    return _with_client(
        confirm_feedback,
        investigation_id=investigation_id,
        candidate_id=candidate_id,
        user_id=user_id,
        comments=comments,
    )


def submit_reject_feedback(
    *,
    investigation_id: str,
    candidate_id: str,
    user_id: str,
    comments: str = "",
) -> FeedbackRecord:
    return _with_client(
        reject_feedback,
        investigation_id=investigation_id,
        candidate_id=candidate_id,
        user_id=user_id,
        comments=comments,
    )


def submit_override_feedback(
    *,
    investigation_id: str,
    candidate_id: str,
    override_candidate_id: str,
    user_id: str,
    comments: str = "",
) -> FeedbackRecord:
    return _with_client(
        override_feedback,
        investigation_id=investigation_id,
        candidate_id=candidate_id,
        override_candidate_id=override_candidate_id,
        user_id=user_id,
        comments=comments,
    )


def fetch_investigation_feedback(investigation_id: str) -> list[FeedbackRecord]:
    return _with_client(get_feedback_for_investigation, investigation_id)
