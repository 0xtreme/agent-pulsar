"""Unit tests for PayrollWorker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import AtomicTask
from agent_pulsar.security.credential_provider import NoopCredentialProvider
from agent_pulsar.workers.base import ExecutionContext
from agent_pulsar.workers.payroll_worker import PayrollWorker


def _make_context(
    task_type: str = "payroll.run",
    params: dict | None = None,  # type: ignore[type-arg]
) -> ExecutionContext:
    task = AtomicTask(
        task_id=uuid4(),
        request_id=uuid4(),
        user_id="test-user",
        conversation_id="test-conv",
        type=task_type,
        params=params or {"company": "easyrun", "period": "2026-03"},
        execution_tier=ExecutionTier.COLD,
        model_assignment="claude-opus-4-0-20250514",
    )

    mock_router = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Payroll processed for 4 employees."
    mock_router.acompletion = AsyncMock(return_value=mock_response)

    return ExecutionContext(
        task=task,
        litellm_router=mock_router,
        model="claude-opus-4-0-20250514",
        credential_provider=NoopCredentialProvider(),
    )


class TestPayrollWorker:
    def test_skill_type(self) -> None:
        assert PayrollWorker().skill_type() == "payroll"

    def test_capability(self) -> None:
        assert PayrollWorker().capability_requirement() == ComplexityTier.COMPLEX

    def test_execution_tier(self) -> None:
        assert PayrollWorker().default_execution_tier() == ExecutionTier.COLD

    async def test_execute_returns_completed(self) -> None:
        worker = PayrollWorker()
        context = _make_context()
        result = await worker.execute(context)

        assert result.status == TaskStatus.COMPLETED
        assert result.task_id == context.task.task_id
        assert result.output is not None
        assert "company" in result.output
        assert result.output["company"] == "easyrun"
        assert result.model_used == "claude-opus-4-0-20250514"
        assert result.execution_tier_used == ExecutionTier.COLD
