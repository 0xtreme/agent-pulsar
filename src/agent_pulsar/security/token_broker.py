"""Token Broker — issues scoped, short-lived JWT tokens backed by Vault secrets.

Workers request tokens from the broker to access external API credentials.
Tokens are JWT-signed, time-limited, and tracked for revocation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import jwt

from agent_pulsar.security.schemas import TokenRequest, TokenResponse
from agent_pulsar.security.vault_client import SecretNotFoundError, VaultError

if TYPE_CHECKING:
    from agent_pulsar.security.vault_client import VaultClient

logger = logging.getLogger(__name__)


class TokenBrokerError(Exception):
    """Base exception for Token Broker operations."""


class TokenNotFoundError(TokenBrokerError):
    """Raised when attempting to revoke an unknown token."""


class TokenExpiredError(TokenBrokerError):
    """Raised when a token has already expired."""


class TokenBroker:
    """Issues and revokes scoped JWT tokens backed by Vault secrets."""

    def __init__(self, vault: VaultClient, signing_secret: str) -> None:
        self._vault = vault
        self._signing_secret = signing_secret
        self._active_tokens: dict[str, dict[str, Any]] = {}  # jti -> metadata

    async def issue_token(self, request: TokenRequest) -> TokenResponse:
        """Issue a scoped JWT token for a worker.

        1. Read the secret from Vault at users/{user_id}/{credential_ref}
        2. Create a JWT with scoped claims
        3. Track the token for revocation
        4. Return token + credential data
        """
        vault_path = f"users/{request.user_id}/{request.credential_ref}"

        try:
            credential_data = await self._vault.read_secret(vault_path)
        except SecretNotFoundError as e:
            raise TokenBrokerError(
                f"No credentials found for user={request.user_id} "
                f"ref={request.credential_ref}"
            ) from e
        except VaultError as e:
            raise TokenBrokerError(f"Vault error: {e}") from e

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=request.ttl_seconds)
        jti = str(uuid4())

        claims = {
            "jti": jti,
            "sub": request.user_id,
            "credential_ref": request.credential_ref,
            "scope": request.scope,
            "iat": now,
            "exp": expires_at,
        }
        token = jwt.encode(claims, self._signing_secret, algorithm="HS256")

        self._active_tokens[jti] = {
            "user_id": request.user_id,
            "credential_ref": request.credential_ref,
            "scope": request.scope,
            "issued_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        logger.info(
            "Issued token jti=%s for user=%s ref=%s scope=%s ttl=%ds",
            jti, request.user_id, request.credential_ref,
            request.scope, request.ttl_seconds,
        )

        return TokenResponse(
            token=token,
            jti=jti,
            expires_at=expires_at,
            credential_data=credential_data,
        )

    async def revoke_token(self, jti: str) -> None:
        """Revoke an active token by its JTI."""
        if jti not in self._active_tokens:
            raise TokenNotFoundError(f"Token not found: {jti}")

        meta = self._active_tokens.pop(jti)
        logger.info(
            "Revoked token jti=%s for user=%s ref=%s",
            jti, meta["user_id"], meta["credential_ref"],
        )

    def is_active(self, jti: str) -> bool:
        """Check if a token is currently active (not revoked)."""
        return jti in self._active_tokens

    @property
    def active_token_count(self) -> int:
        """Number of currently active tokens."""
        return len(self._active_tokens)
