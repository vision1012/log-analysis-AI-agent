"""
Human feedback learning for investigation RCA candidates.

Stores Feedback nodes in the MCP investigation graph (additive; does not alter RCA ranking).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from feedback.feedback_models import (
    CandidateFeedbackCount,
    FeedbackRecord,
    FeedbackType,
)
from graph.neo4j_client import Neo4jClient

DEFAULT_CANDIDATE_LIMIT = 10


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_record(row: dict[str, Any]) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=str(row.get("feedback_id") or ""),
        investigation_id=str(row.get("investigation_id") or ""),
        candidate_id=str(row.get("candidate_id") or ""),
        feedback_type=str(row.get("feedback_type") or ""),
        comments=str(row.get("comments") or ""),
        user_id=str(row.get("user_id") or ""),
        created_at=str(row.get("created_at") or ""),
        override_candidate_id=str(row.get("override_candidate_id") or ""),
    )


_STORE_FEEDBACK_QUERY = """
MERGE (c:RCACandidate {candidate_id: $candidate_id})
ON CREATE SET c.created_at = $created_at
MERGE (u:User {user_id: $user_id})
MERGE (f:Feedback {feedback_id: $feedback_id})
SET f.investigation_id = $investigation_id,
    f.candidate_id = $candidate_id,
    f.feedback_type = $feedback_type,
    f.comments = $comments,
    f.user_id = $user_id,
    f.created_at = $created_at,
    f.override_candidate_id = $override_candidate_id
MERGE (u)-[:SUBMITTED_FEEDBACK]->(f)
MERGE (f)-[:TARGETS_CANDIDATE]->(c)
WITH f
OPTIONAL MATCH (i:Investigation {id: $investigation_id})
FOREACH (_ IN CASE WHEN i IS NOT NULL THEN [1] ELSE [] END |
  MERGE (i)-[:HAS_FEEDBACK]->(f)
)
"""


def record_feedback(
    client: Neo4jClient,
    *,
    investigation_id: str,
    candidate_id: str,
    feedback_type: FeedbackType,
    user_id: str,
    comments: str = "",
    override_candidate_id: str = "",
    feedback_id: str | None = None,
    created_at: str | None = None,
) -> FeedbackRecord:
    """Persist engineer feedback and link Investigation, User, and RCACandidate nodes."""
    fid = feedback_id or str(uuid.uuid4())
    ts = created_at or _utc_now_iso()
    params = {
        "feedback_id": fid,
        "investigation_id": investigation_id,
        "candidate_id": candidate_id,
        "feedback_type": feedback_type.value,
        "comments": comments,
        "user_id": user_id,
        "created_at": ts,
        "override_candidate_id": override_candidate_id,
    }
    client.execute_write(_STORE_FEEDBACK_QUERY, params)
    if override_candidate_id:
        client.execute_write(
            """
            MATCH (f:Feedback {feedback_id: $feedback_id})
            MERGE (oc:RCACandidate {candidate_id: $override_candidate_id})
            MERGE (f)-[:OVERRIDDEN_TO]->(oc)
            """,
            {"feedback_id": fid, "override_candidate_id": override_candidate_id},
        )
    return FeedbackRecord(
        feedback_id=fid,
        investigation_id=investigation_id,
        candidate_id=candidate_id,
        feedback_type=feedback_type.value,
        comments=comments,
        user_id=user_id,
        created_at=ts,
        override_candidate_id=override_candidate_id,
    )


def confirm_feedback(
    client: Neo4jClient,
    *,
    investigation_id: str,
    candidate_id: str,
    user_id: str,
    comments: str = "",
) -> FeedbackRecord:
    return record_feedback(
        client,
        investigation_id=investigation_id,
        candidate_id=candidate_id,
        feedback_type=FeedbackType.CONFIRMED,
        user_id=user_id,
        comments=comments,
    )


def reject_feedback(
    client: Neo4jClient,
    *,
    investigation_id: str,
    candidate_id: str,
    user_id: str,
    comments: str = "",
) -> FeedbackRecord:
    return record_feedback(
        client,
        investigation_id=investigation_id,
        candidate_id=candidate_id,
        feedback_type=FeedbackType.REJECTED,
        user_id=user_id,
        comments=comments,
    )


def override_feedback(
    client: Neo4jClient,
    *,
    investigation_id: str,
    candidate_id: str,
    override_candidate_id: str,
    user_id: str,
    comments: str = "",
) -> FeedbackRecord:
    return record_feedback(
        client,
        investigation_id=investigation_id,
        candidate_id=candidate_id,
        feedback_type=FeedbackType.OVERRIDDEN,
        user_id=user_id,
        comments=comments,
        override_candidate_id=override_candidate_id,
    )


def get_feedback_for_investigation(
    client: Neo4jClient,
    investigation_id: str,
) -> list[FeedbackRecord]:
    """Return all feedback linked to an investigation, newest first."""
    rows = client.execute_read(
        """
        MATCH (f:Feedback)
        WHERE f.investigation_id = $investigation_id
           OR EXISTS {
             MATCH (:Investigation {id: $investigation_id})-[:HAS_FEEDBACK]->(f)
           }
        RETURN f.feedback_id AS feedback_id,
               f.investigation_id AS investigation_id,
               f.candidate_id AS candidate_id,
               f.feedback_type AS feedback_type,
               f.comments AS comments,
               f.user_id AS user_id,
               f.created_at AS created_at,
               f.override_candidate_id AS override_candidate_id
        ORDER BY f.created_at DESC
        """,
        {"investigation_id": investigation_id},
    )
    return [_row_to_record(row) for row in rows]


def get_feedback_by_investigation_ids(
    client: Neo4jClient,
    investigation_ids: list[str],
) -> dict[str, list[FeedbackRecord]]:
    """Batch-load feedback for multiple investigations (similar incident enrichment)."""
    ids = [str(i).strip() for i in investigation_ids if str(i).strip()]
    if not ids:
        return {}

    rows = client.execute_read(
        """
        UNWIND $investigation_ids AS inv_id
        MATCH (f:Feedback)
        WHERE f.investigation_id = inv_id
           OR EXISTS {
             MATCH (:Investigation {id: inv_id})-[:HAS_FEEDBACK]->(f)
           }
        RETURN inv_id AS investigation_id,
               f.feedback_id AS feedback_id,
               f.candidate_id AS candidate_id,
               f.feedback_type AS feedback_type,
               f.comments AS comments,
               f.user_id AS user_id,
               f.created_at AS created_at,
               f.override_candidate_id AS override_candidate_id
        ORDER BY f.created_at DESC
        """,
        {"investigation_ids": ids},
    )

    result: dict[str, list[FeedbackRecord]] = {i: [] for i in ids}
    for row in rows:
        inv_id = str(row.get("investigation_id") or "")
        if inv_id in result:
            result[inv_id].append(_row_to_record(row))
    return result


def get_confirmation_rate(
    client: Neo4jClient,
    *,
    investigation_id: Optional[str] = None,
) -> float:
    """Fraction of feedback events that are CONFIRMED."""
    if investigation_id:
        rows = client.execute_read(
            """
            MATCH (f:Feedback)
            WHERE f.investigation_id = $investigation_id
               OR EXISTS {
                 MATCH (:Investigation {id: $investigation_id})-[:HAS_FEEDBACK]->(f)
               }
            WITH count(f) AS total,
                 sum(CASE WHEN f.feedback_type = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmed
            RETURN CASE WHEN total = 0 THEN 0.0 ELSE toFloat(confirmed) / total END AS rate
            """,
            {"investigation_id": investigation_id},
        )
    else:
        rows = client.execute_read(
            """
            MATCH (f:Feedback)
            WITH count(f) AS total,
                 sum(CASE WHEN f.feedback_type = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmed
            RETURN CASE WHEN total = 0 THEN 0.0 ELSE toFloat(confirmed) / total END AS rate
            """
        )
    return round(float(rows[0].get("rate") or 0.0), 4) if rows else 0.0


def get_rejection_rate(
    client: Neo4jClient,
    *,
    investigation_id: Optional[str] = None,
) -> float:
    """Fraction of feedback events that are REJECTED."""
    if investigation_id:
        rows = client.execute_read(
            """
            MATCH (f:Feedback)
            WHERE f.investigation_id = $investigation_id
               OR EXISTS {
                 MATCH (:Investigation {id: $investigation_id})-[:HAS_FEEDBACK]->(f)
               }
            WITH count(f) AS total,
                 sum(CASE WHEN f.feedback_type = 'REJECTED' THEN 1 ELSE 0 END) AS rejected
            RETURN CASE WHEN total = 0 THEN 0.0 ELSE toFloat(rejected) / total END AS rate
            """,
            {"investigation_id": investigation_id},
        )
    else:
        rows = client.execute_read(
            """
            MATCH (f:Feedback)
            WITH count(f) AS total,
                 sum(CASE WHEN f.feedback_type = 'REJECTED' THEN 1 ELSE 0 END) AS rejected
            RETURN CASE WHEN total = 0 THEN 0.0 ELSE toFloat(rejected) / total END AS rate
            """
        )
    return round(float(rows[0].get("rate") or 0.0), 4) if rows else 0.0


def get_most_confirmed_candidates(
    client: Neo4jClient,
    *,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[CandidateFeedbackCount]:
    rows = client.execute_read(
        """
        MATCH (f:Feedback {feedback_type: 'CONFIRMED'})-[:TARGETS_CANDIDATE]->(c:RCACandidate)
        RETURN c.candidate_id AS candidate_id, count(f) AS count
        ORDER BY count DESC, candidate_id ASC
        LIMIT $limit
        """,
        {"limit": max(1, int(limit))},
    )
    return [
        CandidateFeedbackCount(
            candidate_id=str(row.get("candidate_id") or ""),
            count=int(row.get("count") or 0),
        )
        for row in rows
        if row.get("candidate_id")
    ]


def get_most_rejected_candidates(
    client: Neo4jClient,
    *,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[CandidateFeedbackCount]:
    rows = client.execute_read(
        """
        MATCH (f:Feedback {feedback_type: 'REJECTED'})-[:TARGETS_CANDIDATE]->(c:RCACandidate)
        RETURN c.candidate_id AS candidate_id, count(f) AS count
        ORDER BY count DESC, candidate_id ASC
        LIMIT $limit
        """,
        {"limit": max(1, int(limit))},
    )
    return [
        CandidateFeedbackCount(
            candidate_id=str(row.get("candidate_id") or ""),
            count=int(row.get("count") or 0),
        )
        for row in rows
        if row.get("candidate_id")
    ]
