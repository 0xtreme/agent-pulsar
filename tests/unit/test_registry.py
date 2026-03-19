"""Unit tests for SkillRegistry."""

from __future__ import annotations

from agent_pulsar.supervisor.registry import (
    SkillEntry,
    SkillRegistry,
    create_default_registry,
)


class TestSkillRegistry:
    def test_lookup_matches_prefix(self) -> None:
        reg = SkillRegistry()
        reg.register(SkillEntry("email", "task.backlog.email"))
        entry = reg.lookup("email.send")
        assert entry is not None
        assert entry.topic == "task.backlog.email"

    def test_lookup_longest_prefix_wins(self) -> None:
        reg = SkillRegistry()
        reg.register(SkillEntry("email", "task.backlog.email"))
        reg.register(SkillEntry("email.draft", "task.backlog.email-draft"))
        entry = reg.lookup("email.draft.formal")
        assert entry is not None
        assert entry.topic == "task.backlog.email-draft"

    def test_lookup_no_match_returns_none_without_fallback(self) -> None:
        reg = SkillRegistry()
        reg.register(SkillEntry("email", "task.backlog.email"))
        assert reg.lookup("cooking.recipe") is None

    def test_lookup_no_match_returns_fallback(self) -> None:
        reg = SkillRegistry()
        reg.register(SkillEntry("email", "task.backlog.email"))
        reg.register_fallback(SkillEntry("general", "task.backlog.general"))
        entry = reg.lookup("cooking.recipe")
        assert entry is not None
        assert entry.topic == "task.backlog.general"

    def test_get_topic_uses_fallback(self) -> None:
        reg = SkillRegistry()
        reg.register_fallback(SkillEntry("general", "task.backlog.general"))
        assert reg.get_topic("anything.at_all") == "task.backlog.general"

    def test_get_topic_prefers_specific_over_fallback(self) -> None:
        reg = SkillRegistry()
        reg.register(SkillEntry("email", "task.backlog.email"))
        reg.register_fallback(SkillEntry("general", "task.backlog.general"))
        assert reg.get_topic("email.send") == "task.backlog.email"

    def test_registered_types(self) -> None:
        reg = SkillRegistry()
        reg.register(SkillEntry("email", "task.backlog.email"))
        reg.register(SkillEntry("research", "task.backlog.research"))
        assert reg.registered_types() == ["email", "research"]

    def test_default_registry_has_all_types(self) -> None:
        reg = create_default_registry()
        types = reg.registered_types()
        assert "email" in types
        assert "research" in types
        assert "payroll" in types
        assert "calendar" in types

    def test_default_registry_has_fallback(self) -> None:
        reg = create_default_registry()
        # Unknown type should route to general, not default
        assert reg.get_topic("cooking.recipe") == "task.backlog.general"
