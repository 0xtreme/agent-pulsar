"""One-time link manager — generates and validates ephemeral onboarding tokens.

Links are stored in Redis with a TTL. Each token maps to (user_id, service).
Once used or expired, the link is no longer valid.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

LINK_PREFIX = "ap:onboarding:"


class LinkManager:
    """Generates and validates one-time onboarding links via Redis."""

    def __init__(self, redis: aioredis.Redis, ttl_seconds: int = 600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def generate(self, user_id: str, service: str) -> str:
        """Generate a one-time token for credential onboarding.

        Returns the token string (not the full URL).
        """
        token = secrets.token_urlsafe(32)
        key = f"{LINK_PREFIX}{token}"
        data = json.dumps({"user_id": user_id, "service": service})
        await self._redis.set(key, data, ex=self._ttl)
        logger.info("Generated onboarding link for user=%s service=%s", user_id, service)
        return token

    async def validate(self, token: str) -> dict[str, str] | None:
        """Validate a token and return its metadata (without consuming it).

        Returns None if the token is invalid or expired.
        """
        key = f"{LINK_PREFIX}{token}"
        data = await self._redis.get(key)
        if data is None:
            return None
        result: dict[str, str] = json.loads(data)
        return result

    async def consume(self, token: str) -> dict[str, str] | None:
        """Validate and consume a token (single-use).

        Returns the metadata if valid, None otherwise.
        The token is deleted after consumption.
        """
        key = f"{LINK_PREFIX}{token}"
        data = await self._redis.get(key)
        if data is None:
            return None
        await self._redis.delete(key)
        result: dict[str, str] = json.loads(data)
        return result
