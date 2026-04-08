"""Map JIRA integration exceptions to stable HTTP error responses."""

from __future__ import annotations

from fastapi import HTTPException, status

from api.services.jira_service import (
    JiraAuthError,
    JiraConfigError,
    JiraExternalApiError,
    JiraInvalidSearchError,
    JiraInvalidTicketKeyError,
    JiraNotFoundError,
)

__all__ = ["http_exception_for_jira_integration"]


def http_exception_for_jira_integration(exc: BaseException) -> HTTPException:
    """
    Deterministic mapping for JIRA client errors.

    All responses use ``detail: { "code": str, "message": str }`` for consistency
    with the rest of the API.
    """
    if isinstance(exc, JiraInvalidTicketKeyError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_ticket_key", "message": str(exc)},
        )
    if isinstance(exc, JiraInvalidSearchError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "jira_invalid_search", "message": str(exc)},
        )
    if isinstance(exc, JiraConfigError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "jira_config_missing", "message": str(exc)},
        )
    if isinstance(exc, JiraAuthError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "jira_auth_failed", "message": str(exc)},
        )
    if isinstance(exc, JiraNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "jira_ticket_not_found", "message": str(exc)},
        )
    if isinstance(exc, JiraExternalApiError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "jira_api_failure", "message": str(exc)},
        )
    raise TypeError(f"not a JIRA integration error: {type(exc).__name__}") from exc
