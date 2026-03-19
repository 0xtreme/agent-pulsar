"""Payroll Worker — handles payroll operations via LLM + credentials.

Runs in cold tier (Docker container) for full isolation.
Phase 2: Uses credential_provider for Xero API access.
Actual Xero API calls via MCP come in Phase 3.
"""

from __future__ import annotations

import logging

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import TaskResult
from agent_pulsar.workers.base import ExecutionContext, SkillWorker

logger = logging.getLogger(__name__)

PAYROLL_PROMPT = """\
You are a payroll processing assistant. Process the following payroll task
and return a structured summary.

Task type: {task_type}
Company: {company}
Period: {period}
Additional parameters: {params}

Respond with a clear, structured summary of the payroll operation result.
"""


class PayrollWorker(SkillWorker):
    """Handles payroll.* tasks in cold-tier Docker containers."""

    def skill_type(self) -> str:
        return "payroll"

    def capability_requirement(self) -> ComplexityTier:
        return ComplexityTier.COMPLEX

    def default_execution_tier(self) -> ExecutionTier:
        return ExecutionTier.COLD

    async def execute(self, context: ExecutionContext) -> TaskResult:
        """Process a payroll task using the assigned LLM model."""
        task = context.task
        params = task.params

        # Get credentials if available
        credentials = {}
        if context.credential_provider and task.credential_ref:
            credentials = await context.credential_provider.get_credentials(
                task.credential_ref, "payroll:read"
            )
            logger.info("Obtained payroll credentials for task %s", task.task_id)

        company = params.get("company", "unknown")
        period = params.get("period", "current")

        prompt = PAYROLL_PROMPT.format(
            task_type=task.type,
            company=company,
            period=period,
            params=str(params),
        )

        response = await context.llm_client.acompletion(
            model=context.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1000,
        )

        result_text = (response.choices[0].message.content or "").strip()

        return TaskResult(
            task_id=task.task_id,
            request_id=task.request_id,
            status=TaskStatus.COMPLETED,
            output={
                "summary": result_text,
                "company": company,
                "period": period,
                "has_credentials": bool(credentials),
                "note": "Phase 2: payroll processed via LLM (MCP/Xero integration in Phase 3)",
            },
            model_used=context.model,
            execution_tier_used=task.execution_tier,
        )
