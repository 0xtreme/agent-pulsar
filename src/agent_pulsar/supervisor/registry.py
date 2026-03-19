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

    def lookup(self, task_type: str) -> SkillEntry | None:
        """Find the best matching entry for a task type.

        "email.send" matches prefix "email". Longer prefixes take priority.
        """
        best: SkillEntry | None = None
        for prefix, entry in self._entries.items():
            if task_type.startswith(prefix) and (
                best is None or len(prefix) > len(best.task_type_prefix)
            ):
                    best = entry
        return best

    def get_topic(self, task_type: str) -> str:
        """Return the event bus topic for this task type.

        Falls back to "task.backlog.default" if no match.
        """
        entry = self.lookup(task_type)
        if entry:
            return entry.topic
        logger.warning("No skill registered for %s — using default topic", task_type)
        return "task.backlog.default"

    def all_entries(self) -> list[SkillEntry]:
        """Return all registered entries."""
        return list(self._entries.values())


def create_default_registry() -> SkillRegistry:
    """Create a registry with the default Phase 1 skill entries."""
    registry = SkillRegistry()
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
    return registry
