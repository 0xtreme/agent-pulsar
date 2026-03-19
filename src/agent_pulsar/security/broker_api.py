"""FastAPI router for the Token Broker HTTP API.

Endpoints:
    POST /tokens/issue  — Issue a scoped JWT token
    POST /tokens/revoke — Revoke an active token
    GET  /health        — Broker health check
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from agent_pulsar.security.schemas import RevokeRequest, TokenRequest  # noqa: TC001
from agent_pulsar.security.token_broker import TokenBrokerError, TokenNotFoundError

if TYPE_CHECKING:
    from agent_pulsar.security.token_broker import TokenBroker

logger = logging.getLogger(__name__)

router = APIRouter()

# The broker instance is set during app startup via set_broker()
_broker: TokenBroker | None = None


def set_broker(broker: TokenBroker) -> None:
    """Inject the TokenBroker instance (called during app lifespan)."""
    global _broker  # noqa: PLW0603
    _broker = broker


def _get_broker() -> TokenBroker:
    if _broker is None:
        raise RuntimeError("TokenBroker not initialized")
    return _broker


@router.post("/tokens/issue")
async def issue_token(request: TokenRequest) -> dict[str, Any]:
    """Issue a scoped JWT token backed by Vault credentials."""
    broker = _get_broker()
    try:
        response = await broker.issue_token(request)
    except TokenBrokerError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return response.model_dump(mode="json")


@router.post("/tokens/revoke")
async def revoke_token(request: RevokeRequest) -> dict[str, str]:
    """Revoke a previously issued token."""
    broker = _get_broker()
    try:
        await broker.revoke_token(request.jti)
    except TokenNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {"status": "revoked"}


@router.get("/health")
async def health() -> dict[str, Any]:
    """Token Broker health check."""
    broker = _get_broker()
    return {
        "status": "healthy",
        "active_tokens": broker.active_token_count,
    }
