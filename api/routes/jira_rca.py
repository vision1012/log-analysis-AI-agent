"""JIRA-first RCA run endpoint (ticket + logs -> deterministic RCA)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.services.jira_rca_orchestration_service import (
    EmptyLogContentError,
    JiraRcaOrchestrationError,
    MissingTicketContextError,
    NoUsefulSignalsError,
    RcaUnableToRankCandidateError,
    run_jira_rca,
)
from api.services.jira_service import (
    JiraAuthError,
    JiraConfigError,
    JiraExternalApiError,
    JiraInvalidTicketKeyError,
    JiraNotFoundError,
)
from schemas.jira_rca import JiraRcaRunRequest, JiraRcaRunResponse

router = APIRouter()


@router.post("/jira/rca/run", response_model=JiraRcaRunResponse)
async def run_jira_rca_endpoint(body: JiraRcaRunRequest) -> JiraRcaRunResponse:
    """Run deterministic RCA from JIRA context + uploaded logs."""
    try:
        return run_jira_rca(body)
    except MissingTicketContextError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "missing_ticket_context", "message": str(exc)},
        ) from exc
    except EmptyLogContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_log_content", "message": str(exc)},
        ) from exc
    except NoUsefulSignalsError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "no_useful_signals", "message": str(exc)},
        ) from exc
    except RcaUnableToRankCandidateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "rca_unable_to_rank_candidate", "message": str(exc)},
        ) from exc
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
    except JiraRcaOrchestrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "jira_rca_orchestration_failure", "message": str(exc)},
        ) from exc
