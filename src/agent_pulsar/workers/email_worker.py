"""Email Worker — drafts emails using LLM.

Phase 1: Uses LiteLLM to draft email content. Does NOT actually send
(no MCP/Gmail integration). Real sending comes in Phase 2 with MCP.
"""

from __future__ import annotations

import logging

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import TaskResult
from agent_pulsar.workers.base import ExecutionContext, SkillWorker

logger = logging.getLogger(__name__)

DRAFT_PROMPT = """\
Draft a professional email based on the following parameters.
Return ONLY the email content (subject line + body), no extra commentary.

To: {to}
Subject hint: {subject}
Context: {context}
Tone: {tone}
"""


class EmailWorker(SkillWorker):
    """Handles email.send and email.draft tasks."""

    def skill_type(self) -> str:
        return "email"

    def capability_requirement(self) -> ComplexityTier:
        return ComplexityTier.SIMPLE

    def default_execution_tier(self) -> ExecutionTier:
        return ExecutionTier.HOT

    async def execute(self, context: ExecutionContext) -> TaskResult:
        """Draft an email using the assigned LLM model."""
        task = context.task
        params = task.params

        to = params.get("to", "recipient@example.com")
        subject = params.get("subject", "No subject provided")
        body_context = params.get("context", task.type)
        tone = params.get("tone", "professional")

        prompt = DRAFT_PROMPT.format(
            to=to, subject=subject, context=body_context, tone=tone
        )

        response = await context.litellm_router.acompletion(
            model=context.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500,
        )

        draft = response.choices[0].message.content.strip()

        return TaskResult(
            task_id=task.task_id,
            request_id=task.request_id,
            status=TaskStatus.COMPLETED,
            output={
                "draft": draft,
                "to": to,
                "subject": subject,
                "note": "Phase 1: email drafted but not sent (no MCP integration yet)",
            },
            model_used=context.model,
            execution_tier_used=task.execution_tier,
        )
