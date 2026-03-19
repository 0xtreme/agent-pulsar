"""Event bus abstraction — swappable Redis Streams / Kafka backend."""

from agent_pulsar.event_bus.base import EventBus, MessageHandler
from agent_pulsar.event_bus.redis_streams import RedisStreamsBus

__all__ = ["EventBus", "MessageHandler", "RedisStreamsBus"]
