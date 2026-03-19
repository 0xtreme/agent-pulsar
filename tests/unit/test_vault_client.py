"""Unit tests for Vault client abstraction."""

from __future__ import annotations

import pytest

from agent_pulsar.security.vault_client import (
    MemoryVaultClient,
    SecretNotFoundError,
)


class TestMemoryVaultClient:
    """Tests for the in-memory Vault implementation."""

    async def test_write_and_read(self) -> None:
        vault = MemoryVaultClient()
        await vault.write_secret("users/pavi/xero/payroll", {"api_key": "xk-123"})

        secret = await vault.read_secret("users/pavi/xero/payroll")
        assert secret == {"api_key": "xk-123"}

    async def test_read_nonexistent_raises(self) -> None:
        vault = MemoryVaultClient()
        with pytest.raises(SecretNotFoundError):
            await vault.read_secret("users/pavi/missing")

    async def test_write_overwrites(self) -> None:
        vault = MemoryVaultClient()
        await vault.write_secret("users/pavi/xero/payroll", {"api_key": "old"})
        await vault.write_secret("users/pavi/xero/payroll", {"api_key": "new"})

        secret = await vault.read_secret("users/pavi/xero/payroll")
        assert secret["api_key"] == "new"

    async def test_read_returns_copy(self) -> None:
        vault = MemoryVaultClient()
        await vault.write_secret("path/a", {"key": "val"})

        secret1 = await vault.read_secret("path/a")
        secret1["key"] = "mutated"

        secret2 = await vault.read_secret("path/a")
        assert secret2["key"] == "val"

    async def test_delete(self) -> None:
        vault = MemoryVaultClient()
        await vault.write_secret("path/a", {"key": "val"})
        await vault.delete_secret("path/a")

        with pytest.raises(SecretNotFoundError):
            await vault.read_secret("path/a")

    async def test_delete_nonexistent_no_error(self) -> None:
        vault = MemoryVaultClient()
        await vault.delete_secret("path/nonexistent")  # Should not raise

    async def test_list_secrets(self) -> None:
        vault = MemoryVaultClient()
        await vault.write_secret("users/pavi/xero/payroll", {"k": "v"})
        await vault.write_secret("users/pavi/google/calendar", {"k": "v"})
        await vault.write_secret("users/pavi/slack/bot", {"k": "v"})
        await vault.write_secret("users/other/xero/payroll", {"k": "v"})

        services = await vault.list_secrets("users/pavi")
        assert services == ["google", "slack", "xero"]

    async def test_list_secrets_empty(self) -> None:
        vault = MemoryVaultClient()
        result = await vault.list_secrets("users/nobody")
        assert result == []

    async def test_list_secrets_nested(self) -> None:
        vault = MemoryVaultClient()
        await vault.write_secret("users/pavi/xero/payroll", {"k": "v"})
        await vault.write_secret("users/pavi/xero/invoicing", {"k": "v"})

        scopes = await vault.list_secrets("users/pavi/xero")
        assert scopes == ["invoicing", "payroll"]
