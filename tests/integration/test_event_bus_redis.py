"""Integration tests for RedisStreamsBus against real Redis.

Requires: docker compose up -d (Redis on localhost:6379)
"""

from __future__ import annotations

import asyncio
import contextlib
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from agent_pulsar.event_bus.redis_streams import RedisStreamsBus
from agent_pulsar.schemas.events import TaskRequest

pytestmark = pytest.mark.integration

REDIS_URL = "redis://localhost:6379/1"  # Use DB 1 to avoid colliding with dev


@pytest.fixture
async def bus() -> RedisStreamsBus:
    """Create a connected bus, flush test DB, yield, then close."""
    b = RedisStreamsBus(REDIS_URL, poll_interval_ms=100)
    await b.connect()

    # Flush test DB
    r = aioredis.from_url(REDIS_URL)
    await r.flushdb()
    await r.aclose()

    yield b  # type: ignore[misc]
    await b.close()


class TestRealRedisPublishSubscribe:
    """Test publish/subscribe with real Redis."""

    async def test_publish_and_consume(self, bus: RedisStreamsBus) -> None:
        """Publish a TaskRequest and verify a subscriber receives it."""
        topic = f"test.topic.{uuid4().hex[:8]}"
        received: list[dict] = []

        async def handler(msg_id: str, payload: dict) -> None:  # type: ignore[type-arg]
            received.append(payload)

        # Start subscriber in background
        sub_task = asyncio.create_task(
            bus.subscribe(topic, "test-group", "test-consumer", handler)
        )

        # Give subscriber time to set up
        await asyncio.sleep(0.3)

        # Publish
        request = TaskRequest(
            user_id="test-user",
            conversation_id="test-conv",
            intent="research.summarize",
            raw_message="Test message",
        )
        msg_id = await bus.publish(topic, request)
        assert msg_id

        # Wait for delivery
        await asyncio.sleep(0.5)

        sub_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sub_task

        assert len(received) == 1
        assert received[0]["user_id"] == "test-user"
        assert received[0]["intent"] == "research.summarize"

    async def test_multiple_messages_ordered(self, bus: RedisStreamsBus) -> None:
        """Verify messages arrive in order."""
        topic = f"test.order.{uuid4().hex[:8]}"
        received: list[str] = []

        async def handler(msg_id: str, payload: dict) -> None:  # type: ignore[type-arg]
            received.append(payload["raw_message"])

        sub_task = asyncio.create_task(
            bus.subscribe(topic, "test-group-2", "test-consumer-2", handler)
        )
        await asyncio.sleep(0.3)

        for i in range(5):
            req = TaskRequest(
                user_id="user",
                conversation_id="conv",
                intent="test",
                raw_message=f"msg-{i}",
            )
            await bus.publish(topic, req)

        await asyncio.sleep(1.0)
        sub_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sub_task

        assert received == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]
