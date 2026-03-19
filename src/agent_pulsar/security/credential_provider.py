"""Credential provider — abstraction for workers to obtain scoped credentials.

Workers call get_credentials() to obtain API keys/tokens for external services.
On task completion, release_credentials() revokes the underlying token.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


@runtime_checkable
class CredentialProvider(Protocol):
    """Protocol for obtaining and releasing scoped credentials."""

    async def get_credentials(
        self, credential_ref: str, scope: str
    ) -> dict[str, Any]:
        """Obtain credentials for the given reference and scope."""
        ...

    async def release_credentials(self) -> None:
        """Release all credentials obtained during this task."""
        ...


class NoopCredentialProvider:
    """No-op provider for workers that don't need credentials (Phase 1 workers)."""

    async def get_credentials(
        self, credential_ref: str, scope: str
    ) -> dict[str, Any]:
        return {}

    async def release_credentials(self) -> None:
        pass


class TokenBrokerCredentialProvider:
    """Obtains credentials from the Token Broker HTTP API.

    Issues scoped JWT tokens via POST /tokens/issue, tracks JTIs for
    batch revocation on release_credentials().
    """

    def __init__(self, user_id: str, broker_url: str, ttl_seconds: int = 300) -> None:
        self._user_id = user_id
        self._broker_url = broker_url.rstrip("/")
        self._ttl_seconds = ttl_seconds
        self._active_jtis: list[str] = []

    async def get_credentials(
        self, credential_ref: str, scope: str
    ) -> dict[str, Any]:
        """Request a scoped token from the Token Broker."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._broker_url}/tokens/issue",
                json={
                    "user_id": self._user_id,
                    "credential_ref": credential_ref,
                    "scope": scope,
                    "ttl_seconds": self._ttl_seconds,
                },
                timeout=10.0,
            )
            resp.raise_for_status()

        data = resp.json()
        self._active_jtis.append(data["jti"])
        logger.debug(
            "Obtained credentials for ref=%s scope=%s (jti=%s)",
            credential_ref, scope, data["jti"],
        )
        result: dict[str, Any] = data["credential_data"]
        return result

    async def release_credentials(self) -> None:
        """Revoke all tokens obtained during this task."""
        if not self._active_jtis:
            return

        async with httpx.AsyncClient() as client:
            for jti in self._active_jtis:
                try:
                    resp = await client.post(
                        f"{self._broker_url}/tokens/revoke",
                        json={"jti": jti},
                        timeout=5.0,
                    )
                    resp.raise_for_status()
                    logger.debug("Revoked token jti=%s", jti)
                except Exception as e:
                    logger.warning("Failed to revoke token jti=%s: %s", jti, e)

        self._active_jtis.clear()
