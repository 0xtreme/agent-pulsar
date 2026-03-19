"""Unit tests for the Setup Wizard."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agent_pulsar.setup_wizard.app import app
from agent_pulsar.setup_wizard.checks import CheckResult


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSetupWizardRoutes:
    async def test_index_redirects_to_step_1(self, client: AsyncClient) -> None:
        resp = await client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert "/setup/1" in resp.headers["location"]

    async def test_step_1_renders(self, client: AsyncClient) -> None:
        resp = await client.get("/setup/1")
        assert resp.status_code == 200
        assert "Prerequisites" in resp.text

    async def test_step_2_renders(self, client: AsyncClient) -> None:
        resp = await client.get("/setup/2")
        assert resp.status_code == 200
        assert "Configure" in resp.text

    async def test_step_3_renders(self, client: AsyncClient) -> None:
        resp = await client.get("/setup/3")
        assert resp.status_code == 200
        assert "Start" in resp.text

    async def test_step_4_renders(self, client: AsyncClient) -> None:
        resp = await client.get("/setup/4")
        assert resp.status_code == 200
        assert "Test" in resp.text

    async def test_check_prerequisites_returns_json(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post("/setup/1/check")
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert "all_passed" in data
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) >= 3  # At least docker, uv, api_key


class TestCheckResult:
    def test_passed_check(self) -> None:
        r = CheckResult("Docker", True, "Docker is running")
        assert r.passed
        assert r.name == "Docker"

    def test_failed_check_with_hint(self) -> None:
        r = CheckResult("Docker", False, "Not found", "Install Docker")
        assert not r.passed
        assert r.fix_hint == "Install Docker"
