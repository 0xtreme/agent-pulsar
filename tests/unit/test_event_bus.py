"""Unit tests for the EventBus abstraction and RedisStreamsBus.

Uses fakeredis for testing without a real Redis instance.
"""

from __future__ import annotations

from uuid import uuid4

import fakeredis.aioredis
import pytest

from agent_pulsar.event_bus.redis_streams import DLQ_TOPIC, RedisStreamsBus
from agent_pulsar.schemas.events import TaskRequest


class TestRedisStreamsBusPublish:
    """Test publishing messages to Redis Streams."""

    @pytest.fixture
    async def bus(self) -> RedisStreamsBus:
        bus = RedisStreamsBus("redis://fake", poll_interval_ms=100)
        bus._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        return bus

    async def test_publish_returns_message_id(self, bus: RedisStreamsBus) -> None:
        msg = TaskRequest(
            user_id="u1",
            conversation_id="c1",
            intent="email.send",
            raw_message="Send an email",
        )
        msg_id = await bus.publish("task.submitted", msg)
        assert msg_id is not None
        assert "-" in msg_id  # Redis stream IDs are "timestamp-seq"

    async def test_publish_writes_to_stream(self, bus: RedisStreamsBus) -> None:
        msg = TaskRequest(
            user_id="u1",
            conversation_id="c1",
            intent="research.summarize",
            raw_message="Research AI",
        )
        await bus.publish("task.submitted", msg)

        # Verify the message is in the stream
        entries = await bus.redis.xrange("task.submitted")
        assert len(entries) == 1
        _msg_id, fields = entries[0]
        assert "payload" in fields

    async def test_multiple_publishes(self, bus: RedisStreamsBus) -> None:
        for i in range(5):
            msg = TaskRequest(
                user_id=f"u{i}",
                conversation_id="c1",
                intent="test",
                raw_message=f"Message {i}",
            )
            await bus.publish("test.topic", msg)

        entries = await bus.redis.xrange("test.topic")
        assert len(entries) == 5


class TestRedisStreamsBusConsumerGroup:
    """Test consumer group management."""

    @pytest.fixture
    async def bus(self) -> RedisStreamsBus:
        bus = RedisStreamsBus("redis://fake", poll_interval_ms=100)
        bus._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        return bus

    async def test_ensure_consumer_group_creates(self, bus: RedisStreamsBus) -> None:
        await bus._ensure_consumer_group("test.stream", "test-group")
        # Should not raise — group created successfully
        info = await bus.redis.xinfo_groups("test.stream")
        assert len(info) == 1
        assert info[0]["name"] == "test-group"

    async def test_ensure_consumer_group_idempotent(self, bus: RedisStreamsBus) -> None:
        await bus._ensure_consumer_group("test.stream", "test-group")
        await bus._ensure_consumer_group("test.stream", "test-group")
        # Should not raise — BUSYGROUP is caught


class TestRedisStreamsBusDLQ:
    """Test dead-letter queue functionality."""

    @pytest.fixture
    async def bus(self) -> RedisStreamsBus:
        bus = RedisStreamsBus("redis://fake", poll_interval_ms=100)
        bus._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        return bus

    async def test_move_to_dlq(self, bus: RedisStreamsBus) -> None:
        dlq_id = await bus.move_to_dlq(
            "task.backlog.email",
            {"task_id": str(uuid4()), "type": "email.send"},
            "Connection timeout",
        )
        assert dlq_id is not None

        entries = await bus.redis.xrange(DLQ_TOPIC)
        assert len(entries) == 1


class TestRedisStreamsBusAck:
    """Test message acknowledgement."""

    @pytest.fixture
    async def bus(self) -> RedisStreamsBus:
        bus = RedisStreamsBus("redis://fake", poll_interval_ms=100)
        bus._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        return bus

    async def test_ack_message(self, bus: RedisStreamsBus) -> None:
        # Setup: create stream and group, add a message
        topic = "test.ack"
        group = "test-group"
        consumer = "consumer-1"

        await bus._ensure_consumer_group(topic, group)
        msg = TaskRequest(
            user_id="u", conversation_id="c", intent="test", raw_message="m"
        )
        msg_id = await bus.publish(topic, msg)

        # Read the message via consumer group
        entries = await bus.redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={topic: ">"},
            count=1,
        )
        assert len(entries) > 0

        # Ack it
        await bus.ack(topic, group, msg_id)

        # Verify pending list is empty
        pending = await bus.redis.xpending(topic, group)
        assert pending["pending"] == 0
