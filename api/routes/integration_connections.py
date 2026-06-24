"""Integration connection management API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from api.deps.auth import get_current_user
from integrations.connection_models import (
    IntegrationConnectionCreate,
    IntegrationConnectionSummary,
    IntegrationConnectionUpdate,
    IntegrationConnectionView,
    IntegrationValidationResult,
)
from integrations import connection_service
from schemas.users import UserResponse

router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/connections",
    response_model=IntegrationConnectionView,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration_connection(
    body: IntegrationConnectionCreate,
    current_user: UserResponse = Depends(get_current_user),
) -> IntegrationConnectionView:
    return connection_service.create_connection(current_user, body)


@router.get("/connections", response_model=list[IntegrationConnectionSummary])
async def list_integration_connections(
    workspace_id: Annotated[str | None, Query(min_length=1)] = None,
    current_user: UserResponse = Depends(get_current_user),
) -> list[IntegrationConnectionSummary]:
    return connection_service.list_connection_summaries(current_user, workspace_id)


@router.get("/connections/{connection_id}", response_model=IntegrationConnectionView)
async def get_integration_connection(
    connection_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> IntegrationConnectionView:
    return connection_service.get_connection(current_user, connection_id)


@router.patch("/connections/{connection_id}", response_model=IntegrationConnectionView)
async def patch_integration_connection(
    connection_id: str,
    body: IntegrationConnectionUpdate,
    current_user: UserResponse = Depends(get_current_user),
) -> IntegrationConnectionView:
    return connection_service.update_connection(current_user, connection_id, body)


@router.put("/connections/{connection_id}", response_model=IntegrationConnectionView)
async def put_integration_connection(
    connection_id: str,
    body: IntegrationConnectionUpdate,
    current_user: UserResponse = Depends(get_current_user),
) -> IntegrationConnectionView:
    return connection_service.update_connection(current_user, connection_id, body)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration_connection(
    connection_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> None:
    connection_service.delete_connection(current_user, connection_id)


@router.post(
    "/connections/{connection_id}/validate",
    response_model=IntegrationValidationResult,
)
async def validate_integration_connection(
    connection_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> IntegrationValidationResult:
    return connection_service.validate_connection(current_user, connection_id)
