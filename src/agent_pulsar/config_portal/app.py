"""Config Portal FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
from fastapi import FastAPI

from agent_pulsar.config import get_settings
from agent_pulsar.config_portal.link_manager import LinkManager
from agent_pulsar.config_portal.routes import configure, router
from agent_pulsar.security.vault_client import MemoryVaultClient, VaultClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


def _create_vault(settings: object) -> VaultClient:
    """Create the appropriate Vault client based on settings."""
    vault_url = getattr(settings, "vault_url", None)
    vault_token = getattr(settings, "vault_token", None)
    mount_point = getattr(settings, "vault_mount_point", "secret")

    if vault_url and vault_token:
        from agent_pulsar.security.vault_client import HvacVaultClient

        return HvacVaultClient(url=vault_url, token=vault_token, mount_point=mount_point)
    return MemoryVaultClient()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — initialize and tear down resources."""
    settings = get_settings()

    redis_client = aioredis.from_url(settings.redis_url)
    vault = _create_vault(settings)
    link_manager = LinkManager(
        redis=redis_client,
        ttl_seconds=getattr(settings, "onboarding_link_ttl_seconds", 600),
    )

    configure(
        link_manager=link_manager,
        vault=vault,
        base_url=getattr(settings, "config_portal_base_url", "http://localhost:8102"),
    )

    logger.info("Config Portal started")
    yield

    await redis_client.aclose()
    logger.info("Config Portal stopped")


app = FastAPI(title="Agent Pulsar Config Portal", lifespan=lifespan)
app.include_router(router)
