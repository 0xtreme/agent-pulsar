"""Pydantic models for the Config Portal API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GenerateLinkRequest(BaseModel):
    """Request to generate a one-time onboarding link."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    service: str  # e.g., "xero", "google_calendar", "slack"
    label: str = ""  # Optional human-readable label


class GenerateLinkResponse(BaseModel):
    """Response with the generated onboarding URL."""

    model_config = ConfigDict(frozen=True)

    url: str
    token: str
    expires_in_seconds: int


class CredentialSubmission(BaseModel):
    """API key submission from the onboarding form."""

    model_config = ConfigDict(frozen=True)

    api_key: str
    api_secret: str = ""  # Optional, not all services use it


class ConnectedService(BaseModel):
    """A connected service for a user."""

    model_config = ConfigDict(frozen=True)

    service: str
    connected: bool = True
