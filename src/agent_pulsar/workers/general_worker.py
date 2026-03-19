"""General Worker — catch-all worker for any task type.

Handles arbitrary task types by building a prompt from the task type and
parameters, then calling the LLM to execute. This enables dynamic task
routing — users can ask for anything without predefined task types.
"""

from __future__ import annotations

import json
import logging

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import TaskResult
from agent_pulsar.workers.base import ExecutionContext, SkillWorker

logger = logging.getLogger(__name__)

GENERAL_PROMPT = """\
You are a general-purpose task executor. Complete the following task and
return a clear, structured response.

Task type: {task_type}
Parameters: {params}
Original request context: {raw_context}

Execute the task thoroughly. Provide:
1. A clear result or output
2. Any relevant details, data, or next steps

Be specific and actionable in your response.
"""


class GeneralWorker(SkillWorker):
    """Handles any task type not matched by a specialized worker."""

    def skill_type(self) -> str:
        return "general"

    def capability_requirement(self) -> ComplexityTier:
        return ComplexityTier.MODERATE

    def default_execution_tier(self) -> ExecutionTier:
        return ExecutionTier.HOT

    async def execute(self, context: ExecutionContext) -> TaskResult:
        """Execute an arbitrary task using the assigned LLM model."""
        task = context.task

        # Get credentials if available
        if context.credential_provider and task.credential_ref:
            await context.credential_provider.get_credentials(
                task.credential_ref, f"{task.type.split('.')[0]}:read"
            )

        prompt = GENERAL_PROMPT.format(
            task_type=task.type,
            params=json.dumps(task.params, default=str),
            raw_context=task.params.get("raw_message", task.type),
        )

        response = await context.llm_client.acompletion(
            model=context.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=2000,
        )

        result_text = (response.choices[0].message.content or "").strip()

        return TaskResult(
            task_id=task.task_id,
            request_id=task.request_id,
            status=TaskStatus.COMPLETED,
            output={
                "result": result_text,
                "task_type": task.type,
            },
            model_used=context.model,
            execution_tier_used=task.execution_tier,
        )
