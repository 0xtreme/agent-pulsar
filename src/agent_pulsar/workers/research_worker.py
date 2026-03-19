"""Research Worker — generates research summaries using LLM.

Phase 1: Uses LLM to synthesize research from the model's training data.
Does NOT search the web (no MCP integration). Real web search comes in Phase 2.
"""

from __future__ import annotations

import logging

from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import TaskResult
from agent_pulsar.workers.base import ExecutionContext, SkillWorker

logger = logging.getLogger(__name__)

RESEARCH_PROMPT = """\
Research the following topic and provide a comprehensive summary.

Topic: {topic}
Depth: {depth}
Focus areas: {focus}

Provide:
1. A brief overview (2-3 sentences)
2. Key findings or facts (bullet points)
3. A conclusion or recommendation

Be factual and cite specific details where possible.
"""


class ResearchWorker(SkillWorker):
    """Handles research.summarize and research.analyze tasks."""

    def skill_type(self) -> str:
        return "research"

    def capability_requirement(self) -> ComplexityTier:
        return ComplexityTier.MODERATE

    def default_execution_tier(self) -> ExecutionTier:
        return ExecutionTier.WARM

    async def execute(self, context: ExecutionContext) -> TaskResult:
        """Generate a research summary using the assigned LLM model."""
        task = context.task
        params = task.params

        topic = params.get("topic", task.type)
        depth = params.get("depth", "moderate")
        focus = params.get("focus", "general overview")

        prompt = RESEARCH_PROMPT.format(topic=topic, depth=depth, focus=focus)

        response = await context.llm_client.acompletion(
            model=context.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1500,
        )

        summary = (response.choices[0].message.content or "").strip()

        return TaskResult(
            task_id=task.task_id,
            request_id=task.request_id,
            status=TaskStatus.COMPLETED,
            output={
                "summary": summary,
                "topic": topic,
                "depth": depth,
                "note": "Phase 1: research from model knowledge (no web search yet)",
            },
            model_used=context.model,
            execution_tier_used=task.execution_tier,
        )
