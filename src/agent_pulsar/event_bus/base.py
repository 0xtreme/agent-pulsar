"""Abstract event bus interface.

This abstraction allows swapping Redis Streams (dev) for Kafka (prod)
without changing any calling code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

# Handler signature: (message_id, payload_dict) -> None
MessageHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class EventBus(ABC):
    """Abstract event bus — publish/subscribe with consumer groups."""

    @abstractmethod
    async def connect(self) -> None:
        """Initialize the connection to the underlying transport."""

    @abstractmethod
    async def publish(self, topic: str, message: BaseModel) -> str:
        """Serialize a Pydantic model and publish to a topic.

        Returns the message ID assigned by the transport.
        """

    @abstractmethod
    async def subscribe(
        self,
        topic: str,
        group: str,
        consumer: str,
        handler: MessageHandler,
        *,
        batch_size: int = 1,
    ) -> None:
        """Start consuming from a topic with a consumer group.

        This blocks in an asyncio loop — run via ``asyncio.create_task``.
        The handler receives ``(message_id, payload_dict)``.
        """

    @abstractmethod
    async def ack(self, topic: str, group: str, message_id: str) -> None:
        """Acknowledge successful processing of a message."""

    @abstractmethod
    async def nack(
        self,
        topic: str,
        group: str,
        message_id: str,
        retry_count: int,
        max_retries: int,
    ) -> None:
        """Handle a failed message — re-publish with incremented retry_count
        or move to DLQ if retries exhausted.
        """

    @abstractmethod
    async def move_to_dlq(
        self, topic: str, message: dict[str, Any], error: str
    ) -> str:
        """Move a failed message to the dead-letter queue.

        Returns the DLQ message ID.
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up connections."""
