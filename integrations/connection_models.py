"""Pydantic models for integration connection APIs and services."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_PROVIDERS: frozenset[str] = frozenset(
    {
        "jira",
        "github",
        "gitlab",
        "jenkins",
        "datadog",
        "kubernetes",
        "pagerduty",
        "confluence",
    }
)

PROVIDER_SECRET_FIELDS: dict[str, list[str]] = {
    "jira": ["email", "api_token"],
    "github": ["token"],
    "gitlab": ["token"],
    "jenkins": ["token", "api_token", "password"],
    "datadog": ["api_key", "app_key"],
    "kubernetes": ["token", "kubeconfig"],
    "pagerduty": ["api_token"],
    "confluence": ["email", "api_token"],
}


class IntegrationConnectionSecretPayload(BaseModel):
    """Plaintext credentials submitted on create/update (never stored or returned)."""

    model_config = ConfigDict(extra="ignore")

    email: Optional[str] = None
    api_token: Optional[str] = None
    token: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    app_key: Optional[str] = None
    kubeconfig: Optional[str] = None

    def to_credential_dict(self, provider: str) -> dict[str, str]:
        fields = PROVIDER_SECRET_FIELDS.get(provider, [])
        data: dict[str, str] = {}
        for key in fields:
            value = getattr(self, key, None)
            if value is not None and str(value).strip():
                data[key] = str(value).strip()
        return data


class IntegrationConnectionCreate(BaseModel):
    workspace_id: str = Field(..., min_length=1, max_length=256)
    provider: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=256)
    base_url: Optional[str] = Field(None, max_length=2048)
    org_name: Optional[str] = Field(None, max_length=256)
    project_key: Optional[str] = Field(None, max_length=64)
    repo_name: Optional[str] = Field(None, max_length=256)
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    credentials: IntegrationConnectionSecretPayload

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            allowed = ", ".join(sorted(SUPPORTED_PROVIDERS))
            raise ValueError(f"unsupported provider; allowed: {allowed}")
        return provider

    @field_validator("workspace_id", "display_name", "base_url", "org_name", "project_key", "repo_name", mode="before")
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class IntegrationConnectionUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=256)
    base_url: Optional[str] = Field(None, max_length=2048)
    org_name: Optional[str] = Field(None, max_length=256)
    project_key: Optional[str] = Field(None, max_length=64)
    repo_name: Optional[str] = Field(None, max_length=256)
    config_json: Optional[dict[str, Any]] = None
    is_enabled: Optional[bool] = None
    credentials: Optional[IntegrationConnectionSecretPayload] = None

    @field_validator("display_name", "base_url", "org_name", "project_key", "repo_name", mode="before")
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class IntegrationCredentialsMeta(BaseModel):
    configured: bool = True
    secret_fields: list[str] = Field(default_factory=list)


class IntegrationConnectionView(BaseModel):
    """Public connection metadata (no decrypted secrets)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    provider: str
    display_name: str
    base_url: Optional[str] = None
    org_name: Optional[str] = None
    project_key: Optional[str] = None
    repo_name: Optional[str] = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_validated_at: Optional[datetime] = None
    last_validation_status: Optional[str] = None
    last_validation_error: Optional[str] = None
    credentials: IntegrationCredentialsMeta = Field(default_factory=IntegrationCredentialsMeta)


class IntegrationConnectionListResponse(BaseModel):
    connections: list[IntegrationConnectionView]
    total: int


class IntegrationConnectionSummary(BaseModel):
    """Compact list item for Integrations UI (connection_id + health)."""

    connection_id: str
    provider: str
    workspace_id: str
    display_name: str
    is_enabled: bool = True
    healthy: bool = False


class IntegrationValidationResult(BaseModel):
    connection_id: str
    provider: str
    status: Literal["healthy", "unhealthy"]
    detail: str = ""
    validated_at: datetime
