"""Unit tests for the Config Portal."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent_pulsar.config_portal.link_manager import LinkManager
from agent_pulsar.config_portal.routes import configure, router
from agent_pulsar.security.vault_client import MemoryVaultClient


@pytest.fixture
def vault() -> MemoryVaultClient:
    return MemoryVaultClient()


@pytest.fixture
def link_manager() -> LinkManager:
    """LinkManager with a mock Redis client."""
    mock_redis = AsyncMock()
    store: dict[str, str] = {}

    async def mock_set(key: str, value: str, ex: int = 0) -> None:
        store[key] = value

    async def mock_get(key: str) -> str | None:
        return store.get(key)

    async def mock_delete(key: str) -> None:
        store.pop(key, None)

    mock_redis.set = mock_set
    mock_redis.get = mock_get
    mock_redis.delete = mock_delete

    return LinkManager(redis=mock_redis, ttl_seconds=600)


@pytest.fixture
async def client(
    vault: MemoryVaultClient, link_manager: LinkManager
) -> AsyncClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    configure(link_manager=link_manager, vault=vault, base_url="http://test")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestGenerateLink:
    async def test_generate_returns_url(self, client: AsyncClient) -> None:
        resp = await client.post("/api/links/generate", json={
            "user_id": "pavi",
            "service": "xero",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data
        assert "token" in data
        assert data["url"].startswith("http://test/connect/")
        assert data["expires_in_seconds"] == 600


class TestConnectForm:
    async def test_valid_token_shows_form(
        self, client: AsyncClient, link_manager: LinkManager
    ) -> None:
        token = await link_manager.generate("pavi", "xero")
        resp = await client.get(f"/connect/{token}")
        assert resp.status_code == 200
        assert "xero" in resp.text.lower()

    async def test_invalid_token_shows_error(self, client: AsyncClient) -> None:
        resp = await client.get("/connect/invalid-token")
        assert resp.status_code == 400
        assert "expired" in resp.text.lower() or "invalid" in resp.text.lower()


class TestSubmitCredentials:
    async def test_submit_stores_in_vault(
        self,
        client: AsyncClient,
        link_manager: LinkManager,
        vault: MemoryVaultClient,
    ) -> None:
        token = await link_manager.generate("pavi", "xero")
        resp = await client.post(
            f"/connect/{token}",
            data={"api_key": "xk-123", "api_secret": "xs-456"},
        )
        assert resp.status_code == 200
        assert "connected" in resp.text.lower()

        # Verify stored in Vault
        secret = await vault.read_secret("users/pavi/xero")
        assert secret["api_key"] == "xk-123"
        assert secret["api_secret"] == "xs-456"

    async def test_token_consumed_after_use(
        self,
        client: AsyncClient,
        link_manager: LinkManager,
    ) -> None:
        token = await link_manager.generate("pavi", "slack")
        await client.post(f"/connect/{token}", data={"api_key": "sk-abc"})

        # Second use should fail
        resp = await client.post(f"/connect/{token}", data={"api_key": "sk-def"})
        assert resp.status_code == 400

    async def test_missing_api_key_returns_error(
        self,
        client: AsyncClient,
        link_manager: LinkManager,
    ) -> None:
        token = await link_manager.generate("pavi", "xero")
        resp = await client.post(f"/connect/{token}", data={"api_key": ""})
        assert resp.status_code == 400


class TestConnections:
    async def test_list_connections(
        self, client: AsyncClient, vault: MemoryVaultClient
    ) -> None:
        await vault.write_secret("users/pavi/xero", {"api_key": "x"})
        await vault.write_secret("users/pavi/slack", {"api_key": "s"})

        resp = await client.get("/api/connections/pavi")
        assert resp.status_code == 200
        services = [c["service"] for c in resp.json()]
        assert "xero" in services
        assert "slack" in services

    async def test_disconnect_service(
        self, client: AsyncClient, vault: MemoryVaultClient
    ) -> None:
        await vault.write_secret("users/pavi/xero", {"api_key": "x"})

        resp = await client.delete("/api/connections/pavi/xero")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

        # Verify removed from Vault
        connections = await vault.list_secrets("users/pavi")
        assert "xero" not in connections
