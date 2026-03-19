"""Unit tests for GeneralWorker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import AtomicTask
from agent_pulsar.workers.base import ExecutionContext
from agent_pulsar.workers.general_worker import GeneralWorker


def _make_context(  # type: ignore[type-arg]
    task_type: str = "cooking.find_recipe",
    params: dict | None = None,
) -> ExecutionContext:
    task = AtomicTask(
        task_id=uuid4(),
        request_id=uuid4(),
        user_id="test-user",
        conversation_id="test-conv",
        type=task_type,
        params=params or {"cuisine": "italian", "dish": "pasta"},
        execution_tier=ExecutionTier.HOT,
        model_assignment="claude-sonnet-4-0-20250514",
    )
    mock_router = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Here is a great pasta recipe."
    mock_router.acompletion = AsyncMock(return_value=mock_response)
    return ExecutionContext(
        task=task, llm_client=mock_router, model="claude-sonnet-4-0-20250514",
    )


class TestGeneralWorker:
    def test_skill_type(self) -> None:
        assert GeneralWorker().skill_type() == "general"

    def test_capability(self) -> None:
        assert GeneralWorker().capability_requirement() == ComplexityTier.MODERATE

    def test_execution_tier(self) -> None:
        assert GeneralWorker().default_execution_tier() == ExecutionTier.HOT

    async def test_execute_arbitrary_task(self) -> None:
        worker = GeneralWorker()
        context = _make_context("cooking.find_recipe")
        result = await worker.execute(context)

        assert result.status == TaskStatus.COMPLETED
        assert result.output is not None
        assert result.output["task_type"] == "cooking.find_recipe"
        assert "recipe" in result.output["result"].lower()

    async def test_execute_unknown_task_type(self) -> None:
        worker = GeneralWorker()
        context = _make_context("analytics.forecast_revenue", {"quarter": "Q2"})
        result = await worker.execute(context)

        assert result.status == TaskStatus.COMPLETED
        assert result.output["task_type"] == "analytics.forecast_revenue"

    async def test_execute_preserves_model_info(self) -> None:
        worker = GeneralWorker()
        context = _make_context()
        result = await worker.execute(context)

        assert result.model_used == "claude-sonnet-4-0-20250514"
        assert result.execution_tier_used == ExecutionTier.HOT
