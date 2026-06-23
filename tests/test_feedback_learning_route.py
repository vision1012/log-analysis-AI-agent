"""API route tests for human feedback learning."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from feedback.feedback_models import FeedbackRecord
from schemas.users import UserResponse


def _user() -> UserResponse:
    return UserResponse(
        user_id="user-1",
        first_name="Test",
        last_name="User",
        email="test@example.com",
        created_at=datetime.now(timezone.utc),
    )


def test_confirm_feedback_endpoint() -> None:
    from api.routes.feedback_learning import FeedbackLearningBody, confirm_feedback_endpoint

    record = FeedbackRecord(
        feedback_id="fb-1",
        investigation_id="inv-1",
        candidate_id="c1",
        feedback_type="CONFIRMED",
        user_id="user-1",
        created_at="2024-01-01T00:00:00Z",
    )
    with patch("api.routes.feedback_learning.submit_confirm_feedback", return_value=record):
        body = asyncio.run(
            confirm_feedback_endpoint(
                FeedbackLearningBody(investigation_id="inv-1", candidate_id="c1"),
                current_user=_user(),
            )
        )
    assert body["ok"] is True
    assert body["feedback"]["feedback_type"] == "CONFIRMED"


def test_reject_feedback_endpoint() -> None:
    from api.routes.feedback_learning import FeedbackLearningBody, reject_feedback_endpoint

    record = FeedbackRecord(
        feedback_id="fb-2",
        investigation_id="inv-1",
        candidate_id="c1",
        feedback_type="REJECTED",
        user_id="user-1",
        created_at="2024-01-01T00:00:00Z",
    )
    with patch("api.routes.feedback_learning.submit_reject_feedback", return_value=record):
        body = asyncio.run(
            reject_feedback_endpoint(
                FeedbackLearningBody(
                    investigation_id="inv-1",
                    candidate_id="c1",
                    comments="wrong",
                ),
                current_user=_user(),
            )
        )
    assert body["feedback"]["feedback_type"] == "REJECTED"


def test_override_feedback_endpoint() -> None:
    from api.routes.feedback_learning import OverrideFeedbackBody, override_feedback_endpoint

    record = FeedbackRecord(
        feedback_id="fb-3",
        investigation_id="inv-1",
        candidate_id="c1",
        feedback_type="OVERRIDDEN",
        override_candidate_id="c2",
        user_id="user-1",
        created_at="2024-01-01T00:00:00Z",
    )
    with patch("api.routes.feedback_learning.submit_override_feedback", return_value=record):
        body = asyncio.run(
            override_feedback_endpoint(
                OverrideFeedbackBody(
                    investigation_id="inv-1",
                    candidate_id="c1",
                    override_candidate_id="c2",
                ),
                current_user=_user(),
            )
        )
    assert body["feedback"]["override_candidate_id"] == "c2"


def test_get_investigation_feedback_endpoint() -> None:
    from api.routes.investigation_graph import get_investigation_feedback_endpoint

    records = [
        FeedbackRecord(
            feedback_id="fb-1",
            investigation_id="inv-1",
            candidate_id="c1",
            feedback_type="CONFIRMED",
            user_id="user-1",
            created_at="2024-01-01T00:00:00Z",
        )
    ]
    with patch("api.routes.investigation_graph.fetch_investigation_feedback", return_value=records):
        body = asyncio.run(get_investigation_feedback_endpoint("inv-1"))

    assert body["investigation_id"] == "inv-1"
    assert len(body["feedback"]) == 1
