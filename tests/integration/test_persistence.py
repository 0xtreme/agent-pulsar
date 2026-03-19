"""Integration tests for persistence layer against real PostgreSQL.

Requires: docker compose up -d (PostgreSQL on localhost:5432)
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_pulsar.persistence.models import Base
from agent_pulsar.persistence.repository import TaskRepository
from agent_pulsar.schemas.enums import ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import AtomicTask, TaskRequest

pytestmark = pytest.mark.integration

DB_URL = "postgresql+asyncpg://agent_pulsar:agent_pulsar@localhost:5432/agent_pulsar"


@pytest.fixture
async def repository() -> TaskRepository:
    """Create a repository with a real PostgreSQL connection."""
    engine = create_async_engine(DB_URL)

    # Create tables (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False
    )
    repo = TaskRepository(factory)

    yield repo  # type: ignore[misc]

    await engine.dispose()


class TestRealPostgresPersistence:
    """Test task persistence with real PostgreSQL."""

    async def test_save_and_retrieve_request(
        self, repository: TaskRepository
    ) -> None:
        request = TaskRequest(
            user_id="pavi",
            conversation_id="conv-1",
            intent="research.summarize",
            raw_message="Research AI trends",
        )

        await repository.save_request(request)
        retrieved = await repository.get_request(request.request_id)

        assert retrieved is not None
        assert retrieved.user_id == "pavi"
        assert retrieved.intent == "research.summarize"

    async def test_save_atomic_tasks(self, repository: TaskRepository) -> None:
        request = TaskRequest(
            user_id="pavi",
            conversation_id="conv-2",
            intent="email.send",
            raw_message="Send test email",
        )
        await repository.save_request(request)

        tasks = [
            AtomicTask(
                request_id=request.request_id,
                user_id="pavi",
                conversation_id="conv-2",
                type="email.draft",
                params={"to": "test@example.com"},
                execution_tier=ExecutionTier.HOT,
                model_assignment="claude-haiku-4-5-20250414",
            ),
        ]
        await repository.save_atomic_tasks(tasks)

        # Verify retrieval
        retrieved_tasks = await repository.get_tasks_for_request(
            request.request_id
        )
        assert len(retrieved_tasks) == 1
        assert retrieved_tasks[0].type == "email.draft"

    async def test_update_task_status(self, repository: TaskRepository) -> None:
        request = TaskRequest(
            user_id="pavi",
            conversation_id="conv-3",
            intent="research.analyze",
            raw_message="Analyze something",
        )
        await repository.save_request(request)

        task = AtomicTask(
            request_id=request.request_id,
            user_id="pavi",
            conversation_id="conv-3",
            type="research.analyze",
            params={},
            execution_tier=ExecutionTier.WARM,
            model_assignment="claude-sonnet-4-0-20250514",
        )
        await repository.save_atomic_tasks([task])

        # Update status
        await repository.update_task_status(
            task.task_id,
            TaskStatus.COMPLETED,
            output={"summary": "Test result"},
            duration_ms=1500,
        )

        # Verify
        tasks = await repository.get_tasks_for_request(request.request_id)
        assert tasks[0].status == TaskStatus.COMPLETED.value
        assert tasks[0].output == {"summary": "Test result"}
        assert tasks[0].duration_ms == 1500
