"""Task Scheduler — DAG-aware dispatcher.

Only dispatches tasks whose dependencies are ALL completed. Handles retry
logic and failure cascading.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from agent_pulsar.schemas.enums import TaskStatus
from agent_pulsar.schemas.events import AtomicTask, TaskResult

if TYPE_CHECKING:
    from agent_pulsar.event_bus.base import EventBus
    from agent_pulsar.persistence.repository import TaskRepository
    from agent_pulsar.supervisor.registry import SkillRegistry

logger = logging.getLogger(__name__)


class TaskScheduler:
    """DAG-aware task dispatcher."""

    def __init__(
        self,
        event_bus: EventBus,
        repository: TaskRepository,
        registry: SkillRegistry,
    ) -> None:
        self._event_bus = event_bus
        self._repo = repository
        self._registry = registry

    async def dispatch_ready_tasks(self, request_id: UUID) -> int:
        """Find and dispatch tasks whose dependencies are met.

        Returns the number of tasks dispatched.
        """
        ready_tasks = await self._repo.get_ready_tasks(request_id)
        dispatched = 0

        for record in ready_tasks:
            topic = self._registry.get_topic(record.type)

            # Reconstruct AtomicTask from DB record for serialization
            task = AtomicTask(
                task_id=record.task_id,
                request_id=record.request_id,
                user_id="",  # Not stored on record — from parent request
                conversation_id="",
                type=record.type,
                params=record.params or {},
                dependencies=[UUID(d) for d in (record.dependencies or [])],
                execution_tier=record.execution_tier,
                model_assignment=record.model_assignment,
            )

            await self._event_bus.publish(topic, task)
            await self._repo.update_task_status(record.task_id, TaskStatus.IN_PROGRESS)
            dispatched += 1

            logger.info(
                "Dispatched task %s (%s) → %s",
                record.task_id,
                record.type,
                topic,
            )

        return dispatched

    async def on_task_completed(self, result: TaskResult) -> None:
        """Handle a successful task completion.

        Updates the DB, then tries to release dependent tasks.
        """
        await self._repo.update_task_status(
            result.task_id,
            TaskStatus.COMPLETED,
            output=result.output,
            duration_ms=result.duration_ms,
        )
        logger.info("Task %s completed in %dms", result.task_id, result.duration_ms)

        # Try to dispatch dependent tasks
        count = await self.dispatch_ready_tasks(result.request_id)
        if count > 0:
            logger.info(
                "Released %d dependent tasks for request %s",
                count,
                result.request_id,
            )

    async def on_task_failed(self, result: TaskResult) -> None:
        """Handle a task failure.

        Updates the DB with the error. Retry logic is handled by the event bus
        (nack/re-publish). If the task is permanently failed, mark it in DB.
        """
        await self._repo.update_task_status(
            result.task_id,
            TaskStatus.FAILED,
            error=result.error,
            retry_count=result.retry_count,
            duration_ms=result.duration_ms,
        )
        logger.warning(
            "Task %s failed (retry %d): %s",
            result.task_id,
            result.retry_count,
            result.error,
        )
