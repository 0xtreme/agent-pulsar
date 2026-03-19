"""Vault client abstraction for secret management.

Provides a common interface for reading/writing secrets, with two implementations:
- HvacVaultClient: Real HashiCorp Vault via the hvac library
- MemoryVaultClient: In-memory dict for testing and local development
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class VaultError(Exception):
    """Base exception for Vault operations."""


class SecretNotFoundError(VaultError):
    """Raised when a secret path does not exist."""


class VaultClient(ABC):
    """Abstract interface for secret storage.

    Path convention: users/{user_id}/{service}/{scope}
    Example: users/pavi/xero/payroll
    """

    @abstractmethod
    async def read_secret(self, path: str) -> dict[str, Any]:
        """Read a secret at the given path. Raises SecretNotFoundError if missing."""

    @abstractmethod
    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        """Write or overwrite a secret at the given path."""

    @abstractmethod
    async def delete_secret(self, path: str) -> None:
        """Delete a secret at the given path. No-op if path does not exist."""

    @abstractmethod
    async def list_secrets(self, path: str) -> list[str]:
        """List secret keys under the given path prefix."""


class MemoryVaultClient(VaultClient):
    """In-memory Vault implementation for testing and dev mode.

    Stores secrets in a plain dict. Not persistent across restarts.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def read_secret(self, path: str) -> dict[str, Any]:
        if path not in self._store:
            raise SecretNotFoundError(f"No secret at path: {path}")
        return dict(self._store[path])  # Return a copy

    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        self._store[path] = dict(data)
        logger.debug("MemoryVault: wrote secret at %s", path)

    async def delete_secret(self, path: str) -> None:
        self._store.pop(path, None)
        logger.debug("MemoryVault: deleted secret at %s", path)

    async def list_secrets(self, path: str) -> list[str]:
        prefix = path.rstrip("/") + "/"
        return sorted({
            k[len(prefix):].split("/")[0]
            for k in self._store
            if k.startswith(prefix)
        })


class HvacVaultClient(VaultClient):
    """Real HashiCorp Vault client backed by the hvac library.

    Uses asyncio.to_thread since hvac is synchronous.
    """

    def __init__(self, url: str, token: str, mount_point: str = "secret") -> None:
        import hvac  # type: ignore[import-untyped]

        self._client = hvac.Client(url=url, token=token)
        self._mount_point = mount_point
        if not self._client.is_authenticated():
            raise VaultError(f"Failed to authenticate with Vault at {url}")
        logger.info("Connected to Vault at %s", url)

    async def read_secret(self, path: str) -> dict[str, Any]:
        def _read() -> dict[str, Any]:
            resp = self._client.secrets.kv.v2.read_secret_version(
                path=path, mount_point=self._mount_point
            )
            return resp["data"]["data"]  # type: ignore[no-any-return]

        try:
            return await asyncio.to_thread(_read)
        except Exception as e:
            if "404" in str(e) or "InvalidPath" in type(e).__name__:
                raise SecretNotFoundError(f"No secret at path: {path}") from e
            raise VaultError(f"Vault read failed for {path}: {e}") from e

    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        def _write() -> None:
            self._client.secrets.kv.v2.create_or_update_secret(
                path=path, secret=data, mount_point=self._mount_point
            )

        try:
            await asyncio.to_thread(_write)
            logger.debug("Vault: wrote secret at %s", path)
        except Exception as e:
            raise VaultError(f"Vault write failed for {path}: {e}") from e

    async def delete_secret(self, path: str) -> None:
        def _delete() -> None:
            self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path, mount_point=self._mount_point
            )

        try:
            await asyncio.to_thread(_delete)
            logger.debug("Vault: deleted secret at %s", path)
        except Exception:
            pass  # No-op if path doesn't exist

    async def list_secrets(self, path: str) -> list[str]:
        def _list() -> list[str]:
            resp = self._client.secrets.kv.v2.list_secrets(
                path=path, mount_point=self._mount_point
            )
            keys: list[str] = sorted(resp["data"]["keys"])
            return keys

        try:
            return await asyncio.to_thread(_list)
        except Exception:
            return []
