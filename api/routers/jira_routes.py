"""JIRA ticket ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, status

from api.services.jira_service import (
    JiraAuthError,
    JiraConfigError,
    JiraExternalApiError,
    JiraInvalidTicketKeyError,
    JiraNotFoundError,
    fetch_ticket_context,
)
from schemas.jira import JiraTicketFetchResponse

router = APIRouter()


@router.get("/jira/tickets/{ticket_key}", response_model=JiraTicketFetchResponse)
async def get_jira_ticket_context(
    ticket_key: str = Path(..., min_length=3, description="JIRA ticket key, e.g. PROJ-123"),
) -> JiraTicketFetchResponse:
    """Fetch and normalize a JIRA ticket into backend ticket context."""
    try:
        return fetch_ticket_context(ticket_key)
    except JiraInvalidTicketKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_ticket_key", "message": str(exc)},
        ) from exc
    except JiraConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "jira_config_missing", "message": str(exc)},
        ) from exc
    except JiraAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "jira_auth_failed", "message": str(exc)},
        ) from exc
    except JiraNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "jira_ticket_not_found", "message": str(exc)},
        ) from exc
    except JiraExternalApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "jira_api_failure", "message": str(exc)},
        ) from exc
