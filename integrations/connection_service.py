"""Business logic for workspace integration connections."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from fastapi import HTTPException, status

from db.postgres.connection import get_db_session, get_db_session_readonly
from integrations.connection_models import (
    PROVIDER_SECRET_FIELDS,
    IntegrationConnectionCreate,
    IntegrationConnectionListResponse,
    IntegrationConnectionSummary,
    IntegrationConnectionUpdate,
    IntegrationConnectionView,
    IntegrationCredentialsMeta,
    IntegrationValidationResult,
)
from integrations.connection_repository import (
    IntegrationConnectionNotFoundError,
    count_connections,
    create_connection as repo_create_connection,
    delete_connection as repo_delete_connection,
    get_connection as repo_get_connection,
    get_enabled_connection as repo_get_enabled_connection,
    list_connections as repo_list_connections,
    update_connection as repo_update_connection,
    update_validation_status as repo_update_validation_status,
)
from integrations.credential_encryption import decrypt_credentials, encrypt_credentials, mask_sensitive_text
from schemas.users import UserResponse

logger = logging.getLogger(__name__)

_JIRA_MYSELF_PATH = "/rest/api/3/myself"
_GITHUB_API_BASE = "https://api.github.com"


class IntegrationServiceError(Exception):
    """Base integration service error."""


class IntegrationValidationError(IntegrationServiceError):
    """Raised when provider credential validation fails."""


def assert_workspace_access(user: UserResponse, workspace_id: str) -> None:
    """Ensure the authenticated user may access the workspace."""
    ws = (workspace_id or "").strip()
    if not ws:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "workspace_required", "message": "workspace_id is required"},
        )
    allowed = {user.user_id.strip()}
    if user.team and user.team.strip():
        allowed.add(user.team.strip())
    if ws not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "workspace_forbidden", "message": "access denied for workspace"},
        )


def _credentials_meta(provider: str) -> IntegrationCredentialsMeta:
    return IntegrationCredentialsMeta(
        configured=True,
        secret_fields=list(PROVIDER_SECRET_FIELDS.get(provider, [])),
    )


def _to_view(row: Any) -> IntegrationConnectionView:
    return IntegrationConnectionView(
        id=str(row.id),
        workspace_id=row.workspace_id,
        provider=row.provider,
        display_name=row.display_name,
        base_url=row.base_url,
        org_name=row.org_name,
        project_key=row.project_key,
        repo_name=row.repo_name,
        config_json=dict(row.config_json or {}),
        is_enabled=bool(row.is_enabled),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_validated_at=row.last_validated_at,
        last_validation_status=row.last_validation_status,
        last_validation_error=row.last_validation_error,
        credentials=_credentials_meta(row.provider),
    )


def _require_credentials(provider: str, payload: dict[str, str]) -> dict[str, str]:
    required = PROVIDER_SECRET_FIELDS.get(provider, [])
    if not required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unsupported_provider", "message": f"unsupported provider: {provider}"},
        )
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "credentials_incomplete",
                "message": f"missing credential fields: {', '.join(missing)}",
            },
        )
    return payload


def _to_summary(row: Any) -> IntegrationConnectionSummary:
    status = str(getattr(row, "last_validation_status", "") or "").strip().lower()
    return IntegrationConnectionSummary(
        connection_id=str(row.id),
        provider=str(row.provider),
        workspace_id=str(row.workspace_id),
        display_name=str(row.display_name),
        is_enabled=bool(row.is_enabled),
        healthy=status == "healthy",
    )


def _resolve_workspace_id(user: UserResponse, workspace_id: str | None) -> str:
    ws = (workspace_id or user.team or user.user_id or "").strip()
    if not ws:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "workspace_required", "message": "workspace_id is required"},
        )
    return ws


def create_connection(user: UserResponse, body: IntegrationConnectionCreate) -> IntegrationConnectionView:
    assert_workspace_access(user, body.workspace_id)
    credential_payload = _require_credentials(
        body.provider,
        body.credentials.to_credential_dict(body.provider),
    )
    encrypted = encrypt_credentials(credential_payload)
    with get_db_session() as session:
        row = repo_create_connection(
            session,
            {
                "workspace_id": body.workspace_id,
                "provider": body.provider,
                "display_name": body.display_name,
                "base_url": body.base_url,
                "org_name": body.org_name,
                "project_key": body.project_key,
                "repo_name": body.repo_name,
                "config_json": body.config_json,
                "encrypted_credentials": encrypted,
                "is_enabled": body.is_enabled,
                "created_by": user.user_id,
            },
        )
        return _to_view(row)


def list_connections(user: UserResponse, workspace_id: str) -> IntegrationConnectionListResponse:
    assert_workspace_access(user, workspace_id)
    with get_db_session_readonly() as session:
        rows = repo_list_connections(session, workspace_id)
        views = [_to_view(row) for row in rows]
        total = count_connections(session, workspace_id)
    return IntegrationConnectionListResponse(connections=views, total=total)


def list_connection_summaries(
    user: UserResponse,
    workspace_id: str | None = None,
) -> list[IntegrationConnectionSummary]:
    ws = _resolve_workspace_id(user, workspace_id)
    assert_workspace_access(user, ws)
    with get_db_session_readonly() as session:
        rows = repo_list_connections(session, ws)
        return [_to_summary(row) for row in rows]


def get_connection(user: UserResponse, connection_id: str) -> IntegrationConnectionView:
    with get_db_session_readonly() as session:
        row = repo_get_connection(session, connection_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "connection_not_found", "message": "integration connection not found"},
            )
        assert_workspace_access(user, row.workspace_id)
        return _to_view(row)


def update_connection(
    user: UserResponse,
    connection_id: str,
    body: IntegrationConnectionUpdate,
) -> IntegrationConnectionView:
    with get_db_session() as session:
        row = repo_get_connection(session, connection_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "connection_not_found", "message": "integration connection not found"},
            )
        assert_workspace_access(user, row.workspace_id)

        updates: dict[str, Any] = {}
        for field in (
            "display_name",
            "base_url",
            "org_name",
            "project_key",
            "repo_name",
            "config_json",
            "is_enabled",
        ):
            value = getattr(body, field)
            if value is not None:
                updates[field] = value
        if body.credentials is not None:
            credential_payload = _require_credentials(
                row.provider,
                body.credentials.to_credential_dict(row.provider),
            )
            updates["encrypted_credentials"] = encrypt_credentials(credential_payload)
        row = repo_update_connection(session, connection_id, updates)
        return _to_view(row)


def delete_connection(user: UserResponse, connection_id: str) -> None:
    with get_db_session() as session:
        row = repo_get_connection(session, connection_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "connection_not_found", "message": "integration connection not found"},
            )
        assert_workspace_access(user, row.workspace_id)
        repo_delete_connection(session, connection_id)


def validate_connection(user: UserResponse, connection_id: str) -> IntegrationValidationResult:
    with get_db_session_readonly() as session:
        row = repo_get_connection(session, connection_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "connection_not_found", "message": "integration connection not found"},
            )
        assert_workspace_access(user, row.workspace_id)
        provider = row.provider
        base_url = row.base_url
        org_name = row.org_name
        repo_name = row.repo_name
        credentials = decrypt_credentials(row.encrypted_credentials)

    try:
        validate_provider_credentials(
            provider=provider,
            base_url=base_url,
            org_name=org_name,
            repo_name=repo_name,
            credentials=credentials,
        )
        status_value = "healthy"
        detail = "ok"
        error = None
    except IntegrationValidationError as exc:
        status_value = "unhealthy"
        detail = mask_sensitive_text(str(exc))
        error = detail
        logger.warning(
            "integration.validate.failed connection_id=%s provider=%s",
            connection_id,
            provider,
        )

    validated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_db_session() as session:
        repo_update_validation_status(
            session,
            connection_id,
            status=status_value,
            error=error,
            validated_at=validated_at,
        )

    return IntegrationValidationResult(
        connection_id=connection_id,
        provider=provider,
        status=status_value,  # type: ignore[arg-type]
        detail=detail,
        validated_at=validated_at,
    )


def validate_provider_credentials(
    *,
    provider: str,
    base_url: str | None,
    org_name: str | None,
    repo_name: str | None,
    credentials: dict[str, Any],
) -> None:
    provider_norm = provider.strip().lower()
    if provider_norm == "jira":
        _validate_jira_credentials(base_url, credentials)
        return
    if provider_norm == "github":
        _validate_github_credentials(org_name, repo_name, credentials)
        return
    raise IntegrationValidationError(f"validation not implemented for provider: {provider_norm}")


def resolve_connection_for_provider(
    workspace_id: str,
    provider: str,
    *,
    repo_name: str | None = None,
) -> dict[str, Any] | None:
    """
    Return merged connection config + decrypted credentials for a workspace provider.

    Falls back to None when no enabled DB connection exists (callers may use .env).
    """
    ws = (workspace_id or "").strip()
    if not ws:
        return None
    with get_db_session_readonly() as session:
        row = repo_get_enabled_connection(
            session,
            workspace_id=ws,
            provider=provider,
            repo_name=repo_name,
        )
        if row is None:
            return None
        credentials = decrypt_credentials(row.encrypted_credentials)
    return {
        "connection_id": str(row.id),
        "workspace_id": row.workspace_id,
        "provider": row.provider,
        "display_name": row.display_name,
        "base_url": row.base_url,
        "org_name": row.org_name,
        "project_key": row.project_key,
        "repo_name": row.repo_name,
        "config_json": dict(row.config_json or {}),
        "credentials": credentials,
    }


def _validate_jira_credentials(base_url: str | None, credentials: dict[str, Any]) -> None:
    url = (base_url or "").strip().rstrip("/")
    email = str(credentials.get("email") or "").strip()
    api_token = str(credentials.get("api_token") or "").strip()
    if not url or not email or not api_token:
        raise IntegrationValidationError("Jira base_url, email, and api_token are required")
    parsed = parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise IntegrationValidationError("Jira base_url must be a valid http(s) URL")
    _http_get_json(
        f"{url}{_JIRA_MYSELF_PATH}",
        headers=_jira_auth_headers(email, api_token),
        timeout_sec=_timeout_sec("JIRA_TIMEOUT_SEC", 15),
    )


def _validate_github_credentials(
    org_name: str | None,
    repo_name: str | None,
    credentials: dict[str, Any],
) -> None:
    token = str(credentials.get("token") or "").strip()
    if not token:
        raise IntegrationValidationError("GitHub token is required")
    api_base = (os.environ.get("GITHUB_API_BASE") or _GITHUB_API_BASE).strip().rstrip("/")
    headers = _github_auth_headers(token)
    _http_get_json(f"{api_base}/user", headers=headers, timeout_sec=_timeout_sec("GITHUB_TIMEOUT_SEC", 15))

    org = (org_name or "").strip()
    repo = (repo_name or "").strip()
    if org and repo:
        _http_get_json(
            f"{api_base}/repos/{parse.quote(org)}/{parse.quote(repo)}",
            headers=headers,
            timeout_sec=_timeout_sec("GITHUB_TIMEOUT_SEC", 15),
        )


def _jira_auth_headers(email: str, api_token: str) -> dict[str, str]:
    auth_raw = f"{email}:{api_token}".encode("utf-8")
    auth_header = base64.b64encode(auth_raw).decode("ascii")
    return {
        "Accept": "application/json",
        "Authorization": f"Basic {auth_header}",
    }


def _github_auth_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _timeout_sec(env_name: str, default: int) -> int:
    raw = (os.environ.get(env_name) or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _http_get_json(url: str, *, headers: dict[str, str], timeout_sec: int) -> dict[str, Any]:
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            payload = resp.read().decode("utf-8")
            data = json.loads(payload) if payload else {}
            if not isinstance(data, dict):
                raise IntegrationValidationError("provider returned invalid JSON")
            return data
    except urlerror.HTTPError as exc:
        if exc.code in (401, 403):
            raise IntegrationValidationError("authentication failed") from exc
        if exc.code == 404:
            raise IntegrationValidationError("resource not found") from exc
        raise IntegrationValidationError(f"provider API request failed (status={exc.code})") from exc
    except urlerror.URLError as exc:
        raise IntegrationValidationError("provider API network failure") from exc
    except TimeoutError as exc:
        raise IntegrationValidationError("provider API request timed out") from exc
    except json.JSONDecodeError as exc:
        raise IntegrationValidationError("invalid JSON response from provider") from exc
