"""Redis Streams implementation of the EventBus interface.

Uses redis.asyncio for non-blocking I/O. Messages are serialized as JSON
in a single ``payload`` field within the Redis stream entry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis

from agent_pulsar.event_bus.base import EventBus, MessageHandler

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)

DLQ_TOPIC = "task.dlq"


class RedisStreamsBus(EventBus):
    """EventBus backed by Redis Streams with consumer groups."""

    def __init__(self, redis_url: str, poll_interval_ms: int = 1000) -> None:
        self._redis_url = redis_url
        self._poll_interval_ms = poll_interval_ms
        self._redis: aioredis.Redis | None = None
        self._running = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._redis = aioredis.from_url(
            self._redis_url, decode_responses=True
        )
        logger.info("Connected to Redis at %s", self._redis_url)

    async def close(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()
            logger.info("Redis connection closed")

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("EventBus not connected — call connect() first")
        return self._redis

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, topic: str, message: BaseModel) -> str:
        payload = message.model_dump_json()
        msg_id: str = await self.redis.xadd(
            topic, {"payload": payload}
        )
        logger.debug("Published to %s: %s", topic, msg_id)
        return msg_id

    # ------------------------------------------------------------------
    # Subscribe (blocking consumer loop)
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        topic: str,
        group: str,
        consumer: str,
        handler: MessageHandler,
        *,
        batch_size: int = 1,
    ) -> None:
        await self._ensure_consumer_group(topic, group)
        logger.info(
            "Subscribed to %s (group=%s, consumer=%s)", topic, group, consumer
        )

        while self._running:
            try:
                entries = await self.redis.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={topic: ">"},
                    count=batch_size,
                    block=self._poll_interval_ms,
                )

                if not entries:
                    continue

                for _stream, messages in entries:
                    for msg_id, fields in messages:
                        await self._process_message(
                            topic, group, consumer, msg_id, fields, handler
                        )

            except asyncio.CancelledError:
                logger.info("Consumer %s cancelled", consumer)
                break
            except Exception:
                logger.exception(
                    "Error in consumer loop for %s/%s", topic, consumer
                )
                await asyncio.sleep(2)

    async def _process_message(
        self,
        topic: str,
        group: str,
        consumer: str,
        msg_id: str,
        fields: dict[str, str],
        handler: MessageHandler,
    ) -> None:
        """Process a single message — call handler, ack on success, nack on failure."""
        try:
            payload_str = fields.get("payload", "{}")
            payload = json.loads(payload_str)
            await handler(msg_id, payload)
            await self.ack(topic, group, msg_id)
        except Exception as exc:
            retry_count = int(fields.get("retry_count", "0"))
            max_retries = int(fields.get("max_retries", "3"))
            logger.warning(
                "Handler failed for %s/%s (retry %d/%d): %s",
                topic,
                msg_id,
                retry_count,
                max_retries,
                exc,
            )
            # Ack the original message (we'll re-publish or DLQ)
            await self.ack(topic, group, msg_id)
            await self.nack(topic, group, msg_id, retry_count, max_retries)

    # ------------------------------------------------------------------
    # Ack / Nack / DLQ
    # ------------------------------------------------------------------

    async def ack(self, topic: str, group: str, message_id: str) -> None:
        await self.redis.xack(topic, group, message_id)

    async def nack(
        self,
        topic: str,
        group: str,
        message_id: str,
        retry_count: int,
        max_retries: int,
    ) -> None:
        if retry_count < max_retries:
            # Exponential backoff with jitter before re-publish
            delay = (2**retry_count) + random.uniform(0, 0.5)
            logger.info(
                "Retrying %s (attempt %d/%d) after %.1fs",
                message_id,
                retry_count + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)

            # Re-publish with incremented retry_count
            # Read the original message from the stream
            messages = await self.redis.xrange(topic, min=message_id, max=message_id)
            if messages:
                _id, fields = messages[0]
                fields["retry_count"] = str(retry_count + 1)
                fields["max_retries"] = str(max_retries)
                await self.redis.xadd(topic, fields)
        else:
            # Exhausted retries — move to DLQ
            logger.warning("Moving %s to DLQ after %d retries", message_id, max_retries)
            messages = await self.redis.xrange(topic, min=message_id, max=message_id)
            payload = {}
            if messages:
                _id, fields = messages[0]
                payload_str = fields.get("payload", "{}")
                payload = json.loads(payload_str)
            await self.move_to_dlq(topic, payload, f"Exhausted {max_retries} retries")

    async def move_to_dlq(
        self, topic: str, message: dict[str, Any], error: str
    ) -> str:
        dlq_entry = {
            "payload": json.dumps(
                {
                    "original_topic": topic,
                    "error": error,
                    "data": message,
                    "moved_at": datetime.now(UTC).isoformat(),
                }
            )
        }
        msg_id: str = await self.redis.xadd(DLQ_TOPIC, dlq_entry)  # type: ignore[arg-type]
        logger.info("Moved message to DLQ: %s (from %s)", msg_id, topic)
        return msg_id

    # ------------------------------------------------------------------
    # Consumer group helpers
    # ------------------------------------------------------------------

    async def _ensure_consumer_group(self, topic: str, group: str) -> None:
        """Create consumer group if it doesn't exist. MKSTREAM creates the
        stream if it doesn't exist either."""
        try:
            await self.redis.xgroup_create(
                topic, group, id="0", mkstream=True
            )
            logger.debug("Created consumer group %s on %s", group, topic)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                pass  # Group already exists — expected
            else:
                raise

    async def claim_stale_messages(
        self,
        topic: str,
        group: str,
        consumer: str,
        min_idle_ms: int = 60_000,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Claim messages idle longer than min_idle_ms from other consumers.

        Returns list of (message_id, payload_dict) tuples.
        """
        result = await self.redis.xautoclaim(
            topic, group, consumer, min_idle_time=min_idle_ms, start_id="0"
        )
        # xautoclaim returns (next_start_id, [(id, fields), ...], deleted_ids)
        claimed: list[tuple[str, dict[str, Any]]] = []
        if result and len(result) > 1:
            for msg_id, fields in result[1]:
                payload_str = fields.get("payload", "{}")
                claimed.append((msg_id, json.loads(payload_str)))
        return claimed
