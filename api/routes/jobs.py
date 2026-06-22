"""Job API: Neo4j jobs + PostgreSQL user validation and resolution."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.deps.auth import get_current_user
from api.rate_limit.deps import rate_limit
from schemas.jobs import CreateJobRequest, JobDetailResponse, JobResponse
from services.jobs_service import (
    InvalidTriggeringUserIdError,
    JobConflictError,
    JobNotFoundError,
    UserNotFoundError,
    create_job as create_job_svc,
    get_job_detail,
    list_jobs as list_jobs_svc,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("jobs_post"))],
)
async def create_job(body: CreateJobRequest) -> JobResponse:
    """
    Create a queued job after validating the triggering user exists in PostgreSQL.
    """
    try:
        return create_job_svc(body)
    except UserNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "user_not_found", "message": str(e), "user_id": str(e.user_id)},
        ) from e
    except JobConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "job_conflict", "message": str(e), "job_id": e.job_id},
        ) from e


@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    hydrate_users: bool = Query(
        False,
        description="Reserved for future user hydration on list responses.",
    ),
) -> List[JobResponse]:
    """List jobs (newest first). User hydration is not applied when ``hydrate_users`` is false."""
    return list_jobs_svc(limit=limit, offset=offset, hydrate_users=hydrate_users)


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: str = Path(..., min_length=1, description="Job identifier"),
) -> JobDetailResponse:
    """Return job from Neo4j with user summary from PostgreSQL."""
    try:
        return get_job_detail(job_id)
    except JobNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": str(e), "job_id": e.job_id},
        ) from e
    except InvalidTriggeringUserIdError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_triggering_user_id", "message": str(e), "raw": e.raw},
        ) from e
    except UserNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "user_not_found", "message": str(e), "user_id": str(e.user_id)},
        ) from e
