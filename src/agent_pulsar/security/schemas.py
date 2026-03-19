"""Pydantic models for the Token Broker API."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from pydantic import BaseModel, ConfigDict


class TokenRequest(BaseModel):
    """Request to issue a scoped credential token."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    credential_ref: str  # e.g., "xero/payroll"
    scope: str  # e.g., "payroll:write"
    ttl_seconds: int = 300


class TokenResponse(BaseModel):
    """Response containing the issued token and credential data."""

    model_config = ConfigDict(frozen=True)

    token: str  # JWT
    jti: str  # Token ID for revocation
    expires_at: datetime
    credential_data: dict[str, Any]  # The actual secret from Vault


class RevokeRequest(BaseModel):
    """Request to revoke a previously issued token."""

    model_config = ConfigDict(frozen=True)

    jti: str
