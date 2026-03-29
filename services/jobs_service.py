"""Job orchestration: Neo4j jobs + PostgreSQL user validation and resolution."""

from __future__ import annotations

import uuid
from typing import Any, List, Optional
from uuid import UUID

from neo4j.exceptions import ClientError

from db.neo4j import jobs_repository as neo4j_jobs
from db.postgres.connection import get_db_session_readonly
from db.postgres.repository import get_user_by_id
from schemas.jobs import CreateJobRequest, JobDetailResponse, JobResponse, JobUserSummary


class UserNotFoundError(Exception):
    """Referenced user does not exist in PostgreSQL."""

    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        super().__init__(f"user not found: {user_id}")


class JobNotFoundError(Exception):
    """Job does not exist in Neo4j."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"job not found: {job_id}")


class InvalidTriggeringUserIdError(Exception):
    """``triggered_by_user_id`` on the job is not a valid UUID string."""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        super().__init__(f"invalid triggered_by_user_id: {raw!r}")


class JobConflictError(Exception):
    """Neo4j rejected create (e.g. duplicate ``job_id`` under constraint)."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"job already exists or constraint violation: {job_id}")


def _job_row_to_response(row: dict) -> JobResponse:
    return JobResponse(
        job_id=str(row["job_id"]),
        job_type=str(row["job_type"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        anomaly_id=_optional_str(row.get("anomaly_id")),
        run_id=_optional_str(row.get("run_id")),
        triggered_by_user_id=_optional_str(row.get("triggered_by_user_id")),
        trigger_source=_optional_str(row.get("trigger_source")),
        error_message=_optional_str(row.get("error_message")),
    )


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _parse_user_uuid(raw: object) -> UUID:
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw).strip())
    except ValueError as e:
        raise InvalidTriggeringUserIdError(str(raw)) from e


def create_job(request: CreateJobRequest) -> JobResponse:
    """
    Validate user in PostgreSQL, then create a queued job in Neo4j.
    """
    with get_db_session_readonly() as session:
        user = get_user_by_id(session, request.triggered_by_user_id)
        if user is None:
            raise UserNotFoundError(request.triggered_by_user_id)

    job_id = str(uuid.uuid4())
    neo4j_payload = {
        "job_id": job_id,
        "job_type": request.job_type,
        "anomaly_id": request.anomaly_id,
        "run_id": request.run_id,
        "triggered_by_user_id": str(request.triggered_by_user_id),
        "trigger_source": request.trigger_source,
    }
    try:
        row = neo4j_jobs.create_job(neo4j_payload)
    except ClientError as e:
        code = getattr(e, "code", "") or ""
        if "ConstraintValidationFailed" in code or "Constraint" in code:
            raise JobConflictError(job_id) from e
        raise
    return _job_row_to_response(row)


def get_job_detail(job_id: str) -> JobDetailResponse:
    """Load job from Neo4j and resolve triggering user from PostgreSQL."""
    row = neo4j_jobs.get_job(job_id)
    if row is None:
        raise JobNotFoundError(job_id)

    job = _job_row_to_response(row)
    raw_uid = row.get("triggered_by_user_id")
    if raw_uid is None:
        return JobDetailResponse(job=job, user=None)

    user_uuid = _parse_user_uuid(raw_uid)
    with get_db_session_readonly() as session:
        user = get_user_by_id(session, user_uuid)
        if user is None:
            raise UserNotFoundError(user_uuid)
        summary = JobUserSummary(
            user_id=UUID(str(user.user_id)),
            name=user.name,
            email=user.email,
            role=user.role or "",
            team=user.team,
        )
    return JobDetailResponse(job=job, user=summary)


def list_jobs(
    limit: int = 50,
    offset: int = 0,
    hydrate_users: bool = False,
) -> List[JobResponse]:
    """
    List jobs from Neo4j (newest first).

    ``hydrate_users`` is reserved for future user resolution; currently ignored.
    """
    _ = hydrate_users
    rows = neo4j_jobs.list_jobs(limit=limit, offset=offset)
    return [_job_row_to_response(r) for r in rows]
