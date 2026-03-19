"""Worker Runner — manages the lifecycle of a worker process.

Subscribes to the event bus, deserializes tasks, creates execution contexts,
calls the worker's execute() method, and publishes results back.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from litellm import Router as LiteLLMRouter

from agent_pulsar.event_bus.base import EventBus
from agent_pulsar.schemas.enums import TaskStatus
from agent_pulsar.schemas.events import AtomicTask, TaskResult
from agent_pulsar.workers.base import ExecutionContext, SkillWorker

logger = logging.getLogger(__name__)


class WorkerRunner:
    """Runs a SkillWorker — subscribes to events, executes, publishes results."""

    def __init__(
        self,
        worker: SkillWorker,
        event_bus: EventBus,
        litellm_router: LiteLLMRouter,
        consumer_group: str = "agent-pulsar-workers",
    ) -> None:
        self._worker = worker
        self._event_bus = event_bus
        self._litellm_router = litellm_router
        self._consumer_group = consumer_group

    async def run(self, topic: str) -> None:
        """Main loop — subscribe to topic and process tasks."""
        consumer_name = f"{self._worker.skill_type()}-{uuid4().hex[:8]}"
        logger.info(
            "Starting worker %s on topic %s (group=%s, consumer=%s)",
            self._worker.skill_type(),
            topic,
            self._consumer_group,
            consumer_name,
        )

        await self._event_bus.subscribe(
            topic=topic,
            group=self._consumer_group,
            consumer=consumer_name,
            handler=self._handle_task,
        )

    async def _handle_task(self, msg_id: str, payload: dict[str, Any]) -> None:
        """Process a single task from the event bus."""
        task = AtomicTask.model_validate(payload)
        logger.info(
            "Worker %s executing task %s (%s)",
            self._worker.skill_type(),
            task.task_id,
            task.type,
        )

        start = time.monotonic()

        try:
            # Create a fresh execution context per-task
            context = ExecutionContext(
                task=task,
                litellm_router=self._litellm_router,
                model=task.model_assignment,
            )

            # Execute
            result = await self._worker.execute(context)

            # Publish result
            await self._event_bus.publish("task.results", result)

            elapsed = int((time.monotonic() - start) * 1000)
            logger.info(
                "Task %s completed in %dms (model=%s)",
                task.task_id,
                elapsed,
                task.model_assignment,
            )

        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.error("Task %s failed after %dms: %s", task.task_id, elapsed, e)

            # Publish failure result
            error_result = TaskResult(
                task_id=task.task_id,
                request_id=task.request_id,
                status=TaskStatus.FAILED,
                error=str(e),
                model_used=task.model_assignment,
                execution_tier_used=task.execution_tier,
                duration_ms=elapsed,
            )
            await self._event_bus.publish("task.results", error_result)
