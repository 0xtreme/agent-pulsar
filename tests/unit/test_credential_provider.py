"""Unit tests for credential providers."""

from __future__ import annotations

from agent_pulsar.security.credential_provider import (
    CredentialProvider,
    NoopCredentialProvider,
)


class TestNoopCredentialProvider:
    """Tests for the no-op provider (Phase 1 workers)."""

    async def test_get_credentials_returns_empty(self) -> None:
        provider = NoopCredentialProvider()
        creds = await provider.get_credentials("any/ref", "any:scope")
        assert creds == {}

    async def test_release_is_noop(self) -> None:
        provider = NoopCredentialProvider()
        await provider.release_credentials()  # Should not raise

    async def test_implements_protocol(self) -> None:
        provider = NoopCredentialProvider()
        assert isinstance(provider, CredentialProvider)
