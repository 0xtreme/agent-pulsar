"""Calendar Worker — handles calendar operations via LLM + credentials.

Runs in hot tier for fast reads, warm for modifications.
Phase 2: Uses credential_provider for Google Calendar access.
Actual Google Calendar API calls via MCP come in Phase 3.
"""

from __future__ import annotations

import logging

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import TaskResult
from agent_pulsar.workers.base import ExecutionContext, SkillWorker

logger = logging.getLogger(__name__)

CALENDAR_PROMPT = """\
You are a calendar assistant. Process the following calendar operation
and return a structured response.

Task type: {task_type}
Date/range: {date_range}
Additional parameters: {params}

Respond with a clear, structured summary of the calendar operation result.
"""


class CalendarWorker(SkillWorker):
    """Handles calendar.* tasks."""

    def skill_type(self) -> str:
        return "calendar"

    def capability_requirement(self) -> ComplexityTier:
        return ComplexityTier.SIMPLE

    def default_execution_tier(self) -> ExecutionTier:
        return ExecutionTier.HOT

    async def execute(self, context: ExecutionContext) -> TaskResult:
        """Process a calendar task using the assigned LLM model."""
        task = context.task
        params = task.params

        # Get credentials if available
        if context.credential_provider and task.credential_ref:
            await context.credential_provider.get_credentials(
                task.credential_ref, "calendar:read"
            )
            logger.info("Obtained calendar credentials for task %s", task.task_id)

        date_range = params.get("date", params.get("date_range", "today"))

        prompt = CALENDAR_PROMPT.format(
            task_type=task.type,
            date_range=date_range,
            params=str(params),
        )

        response = await context.litellm_router.acompletion(
            model=context.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )

        result_text = (response.choices[0].message.content or "").strip()

        return TaskResult(
            task_id=task.task_id,
            request_id=task.request_id,
            status=TaskStatus.COMPLETED,
            output={
                "summary": result_text,
                "date_range": date_range,
                "note": "Phase 2: calendar via LLM (MCP/Google Calendar in Phase 3)",
            },
            model_used=context.model,
            execution_tier_used=task.execution_tier,
        )
