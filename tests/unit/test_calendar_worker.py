"""Unit tests for CalendarWorker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import AtomicTask
from agent_pulsar.security.credential_provider import NoopCredentialProvider
from agent_pulsar.workers.base import ExecutionContext
from agent_pulsar.workers.calendar_worker import CalendarWorker


def _make_context(
    task_type: str = "calendar.read",
    params: dict | None = None,  # type: ignore[type-arg]
) -> ExecutionContext:
    task = AtomicTask(
        task_id=uuid4(),
        request_id=uuid4(),
        user_id="test-user",
        conversation_id="test-conv",
        type=task_type,
        params=params or {"date": "2026-03-19"},
        execution_tier=ExecutionTier.HOT,
        model_assignment="claude-haiku-4-5-20250414",
    )

    mock_router = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "You have 3 meetings today."
    mock_router.acompletion = AsyncMock(return_value=mock_response)

    return ExecutionContext(
        task=task,
        llm_client=mock_router,
        model="claude-haiku-4-5-20250414",
        credential_provider=NoopCredentialProvider(),
    )


class TestCalendarWorker:
    def test_skill_type(self) -> None:
        assert CalendarWorker().skill_type() == "calendar"

    def test_capability(self) -> None:
        assert CalendarWorker().capability_requirement() == ComplexityTier.SIMPLE

    def test_execution_tier(self) -> None:
        assert CalendarWorker().default_execution_tier() == ExecutionTier.HOT

    async def test_execute_returns_completed(self) -> None:
        worker = CalendarWorker()
        context = _make_context()
        result = await worker.execute(context)

        assert result.status == TaskStatus.COMPLETED
        assert result.task_id == context.task.task_id
        assert result.output is not None
        assert "date_range" in result.output
        assert result.output["date_range"] == "2026-03-19"
        assert result.model_used == "claude-haiku-4-5-20250414"
        assert result.execution_tier_used == ExecutionTier.HOT
