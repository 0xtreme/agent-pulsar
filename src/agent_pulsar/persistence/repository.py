"""Task repository — CRUD operations for task state in PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from agent_pulsar.persistence.models import AtomicTaskRecord, TaskRequestRecord
from agent_pulsar.schemas.enums import TaskStatus

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from agent_pulsar.schemas.events import AtomicTask, TaskRequest


class TaskRepository:
    """Data access layer for task requests and atomic tasks."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Task Requests
    # ------------------------------------------------------------------

    async def save_request(self, request: TaskRequest) -> None:
        """Persist a high-level task request."""
        record = TaskRequestRecord(
            request_id=request.request_id,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            intent=request.intent,
            raw_message=request.raw_message,
            params=request.params,
            priority=request.priority.value,
            status=TaskStatus.CLAIMED.value,
            created_at=request.created_at,
        )
        async with self._session_factory() as session:
            session.add(record)
            await session.commit()

    async def get_request(self, request_id: UUID) -> TaskRequestRecord | None:
        """Fetch a task request by ID."""
        async with self._session_factory() as session:
            return await session.get(TaskRequestRecord, request_id)

    async def update_request_status(
        self, request_id: UUID, status: TaskStatus
    ) -> None:
        """Update the status of a request."""
        async with self._session_factory() as session:
            stmt = (
                update(TaskRequestRecord)
                .where(TaskRequestRecord.request_id == request_id)
                .values(
                    status=status.value,
                    completed_at=(
                        datetime.now(UTC)
                        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                        else None
                    ),
                )
            )
            await session.execute(stmt)
            await session.commit()

    # ------------------------------------------------------------------
    # Atomic Tasks
    # ------------------------------------------------------------------

    async def save_atomic_tasks(self, tasks: list[AtomicTask]) -> None:
        """Persist a batch of decomposed atomic tasks."""
        records = [
            AtomicTaskRecord(
                task_id=t.task_id,
                request_id=t.request_id,
                type=t.type,
                params=t.params,
                dependencies=[str(d) for d in t.dependencies],
                status=TaskStatus.PENDING.value,
                execution_tier=t.execution_tier.value,
                model_assignment=t.model_assignment,
                created_at=t.created_at,
            )
            for t in tasks
        ]
        async with self._session_factory() as session:
            session.add_all(records)
            await session.commit()

    async def update_task_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        *,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
        retry_count: int | None = None,
    ) -> None:
        """Update the status and result of an atomic task."""
        values: dict[str, Any] = {"status": status.value}
        if output is not None:
            values["output"] = output
        if error is not None:
            values["error"] = error
        if duration_ms is not None:
            values["duration_ms"] = duration_ms
        if retry_count is not None:
            values["retry_count"] = retry_count
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            values["completed_at"] = datetime.now(UTC)

        async with self._session_factory() as session:
            stmt = (
                update(AtomicTaskRecord)
                .where(AtomicTaskRecord.task_id == task_id)
                .values(**values)
            )
            await session.execute(stmt)
            await session.commit()

    async def get_tasks_for_request(
        self, request_id: UUID
    ) -> list[AtomicTaskRecord]:
        """Return all atomic tasks for a given request."""
        async with self._session_factory() as session:
            stmt = select(AtomicTaskRecord).where(
                AtomicTaskRecord.request_id == request_id
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_ready_tasks(self, request_id: UUID) -> list[AtomicTaskRecord]:
        """Return tasks whose dependencies are ALL completed and status is PENDING.

        A task is "ready" if:
        1. Its status is PENDING
        2. Every UUID in its dependencies list corresponds to a COMPLETED task
        """
        all_tasks = await self.get_tasks_for_request(request_id)

        completed_ids = {
            str(t.task_id)
            for t in all_tasks
            if t.status == TaskStatus.COMPLETED.value
        }

        ready = []
        for task in all_tasks:
            if task.status != TaskStatus.PENDING.value:
                continue
            deps = task.dependencies or []
            if all(dep_id in completed_ids for dep_id in deps):
                ready.append(task)
        return ready

    async def all_tasks_terminal(self, request_id: UUID) -> bool:
        """True if every task for a request is COMPLETED or FAILED."""
        tasks = await self.get_tasks_for_request(request_id)
        if not tasks:
            return False
        terminal = {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}
        return all(t.status in terminal for t in tasks)
