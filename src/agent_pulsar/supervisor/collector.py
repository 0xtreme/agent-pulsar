"""Result Collector — aggregates results and publishes CompletionEvent.

When all tasks for a request are terminal (COMPLETED or FAILED), the collector
generates a user-facing summary and notifies OpenClaw via webhook.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from agent_pulsar.schemas.enums import TaskStatus
from agent_pulsar.schemas.events import CompletionEvent, TaskResult

if TYPE_CHECKING:
    from agent_pulsar.llm.client import LLMClient
    from agent_pulsar.event_bus.base import EventBus
    from agent_pulsar.persistence.repository import TaskRepository

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """\
Summarize the following task results in 1-2 sentences for the user.
Be concise and friendly. Focus on what was accomplished.

Task results:
{results_json}
"""


class ResultCollector:
    """Collects results and publishes CompletionEvent when all tasks are done."""

    def __init__(
        self,
        event_bus: EventBus,
        repository: TaskRepository,
        llm_client: LLMClient,
        openclaw_webhook_url: str,
    ) -> None:
        self._event_bus = event_bus
        self._repo = repository
        self._client = llm_client
        self._webhook_url = openclaw_webhook_url

    async def handle_result(self, result: TaskResult) -> None:
        """Process a task result. If all tasks for the request are done,
        generate summary and publish CompletionEvent."""
        # Check if all tasks for this request are terminal
        all_done = await self._repo.all_tasks_terminal(result.request_id)
        if not all_done:
            return

        # All tasks done — build completion event
        all_tasks = await self._repo.get_tasks_for_request(result.request_id)
        request = await self._repo.get_request(result.request_id)

        if not request:
            logger.error("Request %s not found for completion", result.request_id)
            return

        # Determine overall status
        all_completed = all(t.status == TaskStatus.COMPLETED.value for t in all_tasks)
        overall_status = TaskStatus.COMPLETED if all_completed else TaskStatus.FAILED

        # Build result list
        results = [
            TaskResult(
                task_id=t.task_id,
                request_id=t.request_id,
                status=TaskStatus(t.status),
                output=t.output or {},
                error=t.error,
                duration_ms=t.duration_ms or 0,
            )
            for t in all_tasks
        ]

        # Generate summary
        summary = await self._generate_summary(results)

        total_duration = sum(t.duration_ms or 0 for t in all_tasks)

        event = CompletionEvent(
            request_id=result.request_id,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            status=overall_status,
            summary=summary,
            results=results,
            total_duration_ms=total_duration,
        )

        # Publish to event bus
        await self._event_bus.publish("task.completed", event)

        # Update request status
        await self._repo.update_request_status(result.request_id, overall_status)

        # Notify OpenClaw via webhook
        await self._notify_openclaw(event)

        logger.info(
            "Request %s completed: %s (%d tasks, %dms)",
            result.request_id,
            overall_status.value,
            len(results),
            total_duration,
        )

    async def _generate_summary(self, results: list[TaskResult]) -> str:
        """Call Haiku to generate a user-facing summary."""
        try:
            results_json = "\n".join(
                f"- {r.status.value}: {r.output}" for r in results
            )
            response = await self._client.acompletion(
                model="fast-model",
                messages=[
                    {
                        "role": "user",
                        "content": SUMMARY_PROMPT.format(results_json=results_json),
                    }
                ],
                temperature=0.3,
                max_tokens=200,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("Summary generation failed: %s", e)
            completed = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
            return f"Completed {completed}/{len(results)} tasks."

    async def _notify_openclaw(self, event: CompletionEvent) -> None:
        """POST completion event to OpenClaw's /hooks/agent webhook."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = {
                    "agentId": "agent-pulsar",
                    "channel": event.conversation_id,
                    "message": event.summary,
                    "data": {
                        "request_id": str(event.request_id),
                        "status": event.status.value,
                        "total_duration_ms": event.total_duration_ms,
                    },
                }
                response = await client.post(self._webhook_url, json=payload)
                if response.status_code < 300:
                    logger.info("OpenClaw webhook delivered for %s", event.request_id)
                else:
                    logger.warning(
                        "OpenClaw webhook returned %d for %s",
                        response.status_code,
                        event.request_id,
                    )
        except Exception as e:
            # Non-fatal — the event is still on the bus
            logger.error("OpenClaw webhook failed for %s: %s", event.request_id, e)
