"""Shared test fixtures for Agent Pulsar tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from agent_pulsar.event_bus.redis_streams import RedisStreamsBus


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """Create a fake Redis instance for unit tests."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_event_bus(fake_redis: fakeredis.aioredis.FakeRedis) -> RedisStreamsBus:
    """Create a RedisStreamsBus backed by fake Redis."""
    bus = RedisStreamsBus("redis://fake", poll_interval_ms=100)
    bus._redis = fake_redis
    return bus


@pytest.fixture
def mock_litellm_router() -> MagicMock:
    """Create a mock LiteLLM Router."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"complexity": "moderate"}'
    mock.acompletion = AsyncMock(return_value=mock_response)
    return mock
