"""Skill Registry — maps task types to worker capabilities, topics, and defaults.

The registry is the routing table that tells the Supervisor where to send
each type of task and what execution constraints apply.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillEntry:
    """Registration for a worker skill type."""

    task_type_prefix: str       # e.g. "email" matches "email.send", "email.draft"
    topic: str                  # e.g. "task.backlog.email"
    default_tier: ExecutionTier = ExecutionTier.HOT
    min_capability: ComplexityTier = ComplexityTier.SIMPLE


class SkillRegistry:
    """Maps task types to worker topics and execution constraints."""

    def __init__(self) -> None:
        self._entries: dict[str, SkillEntry] = {}
        self._fallback: SkillEntry | None = None

    def register(self, entry: SkillEntry) -> None:
        """Register a skill entry."""
        self._entries[entry.task_type_prefix] = entry
        logger.info(
            "Registered skill: %s → %s (tier=%s, min=%s)",
            entry.task_type_prefix,
            entry.topic,
            entry.default_tier.value,
            entry.min_capability.value,
        )

    def register_fallback(self, entry: SkillEntry) -> None:
        """Register a catch-all fallback for unmatched task types."""
        self._fallback = entry
        logger.info("Registered fallback skill: %s → %s", entry.task_type_prefix, entry.topic)

    def lookup(self, task_type: str) -> SkillEntry | None:
        """Find the best matching entry for a task type.

        "email.send" matches prefix "email". Longer prefixes take priority.
        Falls back to the registered fallback if no prefix matches.
        """
        best: SkillEntry | None = None
        for prefix, entry in self._entries.items():
            if task_type.startswith(prefix) and (
                best is None or len(prefix) > len(best.task_type_prefix)
            ):
                best = entry
        return best or self._fallback

    def get_topic(self, task_type: str) -> str:
        """Return the event bus topic for this task type.

        Falls back to the general worker topic, or "task.backlog.default" as last resort.
        """
        entry = self.lookup(task_type)
        if entry:
            return entry.topic
        logger.warning("No skill registered for %s — using default topic", task_type)
        return "task.backlog.default"

    def all_entries(self) -> list[SkillEntry]:
        """Return all registered entries (excluding fallback)."""
        return list(self._entries.values())

    def registered_types(self) -> list[str]:
        """Return all registered task type prefixes."""
        return sorted(self._entries.keys())


def create_default_registry() -> SkillRegistry:
    """Create a registry with all registered skill entries."""
    registry = SkillRegistry()
    # Phase 1
    registry.register(
        SkillEntry(
            task_type_prefix="email",
            topic="task.backlog.email",
            default_tier=ExecutionTier.HOT,
            min_capability=ComplexityTier.SIMPLE,
        )
    )
    registry.register(
        SkillEntry(
            task_type_prefix="research",
            topic="task.backlog.research",
            default_tier=ExecutionTier.WARM,
            min_capability=ComplexityTier.MODERATE,
        )
    )
    # Phase 2
    registry.register(
        SkillEntry(
            task_type_prefix="payroll",
            topic="task.backlog.payroll",
            default_tier=ExecutionTier.COLD,
            min_capability=ComplexityTier.COMPLEX,
        )
    )
    registry.register(
        SkillEntry(
            task_type_prefix="calendar",
            topic="task.backlog.calendar",
            default_tier=ExecutionTier.HOT,
            min_capability=ComplexityTier.SIMPLE,
        )
    )
    # Catch-all: general-purpose worker for any unregistered task type
    registry.register_fallback(
        SkillEntry(
            task_type_prefix="general",
            topic="task.backlog.general",
            default_tier=ExecutionTier.HOT,
            min_capability=ComplexityTier.MODERATE,
        )
    )
    return registry
