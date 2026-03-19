"""Unit tests for the Token Broker."""

from __future__ import annotations

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from agent_pulsar.security.broker_api import router, set_broker
from agent_pulsar.security.schemas import TokenRequest
from agent_pulsar.security.token_broker import (
    TokenBroker,
    TokenBrokerError,
    TokenNotFoundError,
)
from agent_pulsar.security.vault_client import MemoryVaultClient

SIGNING_SECRET = "test-secret-key"


@pytest.fixture
def vault() -> MemoryVaultClient:
    return MemoryVaultClient()


@pytest.fixture
async def broker(vault: MemoryVaultClient) -> TokenBroker:
    # Seed a test credential
    await vault.write_secret("users/pavi/xero/payroll", {
        "api_key": "xk-test-123",
        "api_secret": "xs-test-456",
    })
    return TokenBroker(vault=vault, signing_secret=SIGNING_SECRET)


class TestTokenBrokerIssue:
    """Tests for token issuance."""

    async def test_issue_returns_valid_jwt(self, broker: TokenBroker) -> None:
        request = TokenRequest(
            user_id="pavi",
            credential_ref="xero/payroll",
            scope="payroll:write",
            ttl_seconds=60,
        )
        response = await broker.issue_token(request)

        # Verify JWT can be decoded
        decoded = jwt.decode(response.token, SIGNING_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == "pavi"
        assert decoded["credential_ref"] == "xero/payroll"
        assert decoded["scope"] == "payroll:write"
        assert decoded["jti"] == response.jti

    async def test_issue_returns_credential_data(self, broker: TokenBroker) -> None:
        request = TokenRequest(
            user_id="pavi",
            credential_ref="xero/payroll",
            scope="payroll:read",
        )
        response = await broker.issue_token(request)

        assert response.credential_data["api_key"] == "xk-test-123"
        assert response.credential_data["api_secret"] == "xs-test-456"

    async def test_issue_tracks_active_token(self, broker: TokenBroker) -> None:
        request = TokenRequest(
            user_id="pavi",
            credential_ref="xero/payroll",
            scope="payroll:read",
        )
        assert broker.active_token_count == 0

        response = await broker.issue_token(request)

        assert broker.active_token_count == 1
        assert broker.is_active(response.jti)

    async def test_issue_missing_credential_raises(self, broker: TokenBroker) -> None:
        request = TokenRequest(
            user_id="pavi",
            credential_ref="slack/bot",
            scope="chat:write",
        )
        with pytest.raises(TokenBrokerError, match="No credentials found"):
            await broker.issue_token(request)


class TestTokenBrokerRevoke:
    """Tests for token revocation."""

    async def test_revoke_removes_token(self, broker: TokenBroker) -> None:
        request = TokenRequest(
            user_id="pavi",
            credential_ref="xero/payroll",
            scope="payroll:read",
        )
        response = await broker.issue_token(request)
        assert broker.is_active(response.jti)

        await broker.revoke_token(response.jti)

        assert not broker.is_active(response.jti)
        assert broker.active_token_count == 0

    async def test_revoke_unknown_raises(self, broker: TokenBroker) -> None:
        with pytest.raises(TokenNotFoundError):
            await broker.revoke_token("nonexistent-jti")


class TestTokenBrokerAPI:
    """Tests for the FastAPI endpoints."""

    @pytest.fixture
    async def client(self, broker: TokenBroker) -> AsyncClient:
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        set_broker(broker)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def test_issue_endpoint(self, client: AsyncClient) -> None:
        resp = await client.post("/tokens/issue", json={
            "user_id": "pavi",
            "credential_ref": "xero/payroll",
            "scope": "payroll:write",
            "ttl_seconds": 120,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert "jti" in data
        assert "credential_data" in data

    async def test_issue_missing_credential_returns_400(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post("/tokens/issue", json={
            "user_id": "pavi",
            "credential_ref": "missing/service",
            "scope": "read",
        })
        assert resp.status_code == 400

    async def test_revoke_endpoint(self, client: AsyncClient) -> None:
        # Issue first
        issue_resp = await client.post("/tokens/issue", json={
            "user_id": "pavi",
            "credential_ref": "xero/payroll",
            "scope": "payroll:write",
        })
        jti = issue_resp.json()["jti"]

        # Revoke
        resp = await client.post("/tokens/revoke", json={"jti": jti})
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    async def test_revoke_unknown_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post("/tokens/revoke", json={"jti": "fake-jti"})
        assert resp.status_code == 404

    async def test_health_endpoint(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
