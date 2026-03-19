"""Task Decomposer — uses Opus to break high-level requests into atomic sub-tasks.

For simple, single-step requests, returns a single AtomicTask.
For complex requests, returns a DAG of AtomicTasks with dependency UUIDs.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from litellm import Router

from agent_pulsar.schemas.enums import ExecutionTier, Priority
from agent_pulsar.schemas.events import AtomicTask, TaskRequest

logger = logging.getLogger(__name__)

DECOMPOSITION_PROMPT = """\
You are a task decomposition engine. Given a user request, break it into
atomic sub-tasks that can be executed independently by specialized workers.

Available worker types:
- email.send: Send an email
- email.draft: Draft an email without sending
- research.summarize: Research a topic and produce a summary
- research.analyze: Deep analysis of a topic

Rules:
1. Each sub-task must have a "type" matching one of the available worker types.
2. Each sub-task has "params" (a dict with task-specific parameters).
3. If tasks have dependencies, specify "depends_on" as indices (0-based) into the task array.
4. Keep it minimal — don't over-decompose simple requests.
5. A single-step request should return exactly ONE task with no dependencies.

User request: {raw_message}
Intent: {intent}
Parameters: {params}

Respond with ONLY a JSON array of tasks:
[
  {{"type": "...", "params": {{...}}, "depends_on": []}},
  {{"type": "...", "params": {{...}}, "depends_on": [0]}}
]
"""


class TaskDecomposer:
    """Decomposes high-level requests into atomic sub-task DAGs."""

    def __init__(
        self,
        litellm_router: Router,
        model: str = "claude-opus-4-0-20250514",
    ) -> None:
        self._router = litellm_router
        self._model = model

    async def decompose(self, request: TaskRequest) -> list[AtomicTask]:
        """Break a TaskRequest into a list of AtomicTasks.

        Returns at least one task. Dependencies are expressed as UUIDs.
        """
        try:
            raw_tasks = await self._call_llm(request)
            return self._build_atomic_tasks(request, raw_tasks)
        except Exception as e:
            logger.error("Decomposition failed: %s. Creating single fallback task.", e)
            return self._fallback_single_task(request)

    async def _call_llm(self, request: TaskRequest) -> list[dict[str, Any]]:
        """Call Opus to decompose the request."""
        prompt = DECOMPOSITION_PROMPT.format(
            raw_message=request.raw_message,
            intent=request.intent,
            params=json.dumps(request.params, default=str)[:1000],
        )
        response = await self._router.acompletion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=2000,
        )
        content = response.choices[0].message.content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            content = content.rsplit("```", 1)[0]

        tasks = json.loads(content)
        if not isinstance(tasks, list) or len(tasks) == 0:
            raise ValueError("LLM returned empty or non-list response")
        return tasks

    def _build_atomic_tasks(
        self, request: TaskRequest, raw_tasks: list[dict[str, Any]]
    ) -> list[AtomicTask]:
        """Convert raw LLM output into AtomicTask objects with proper UUIDs."""
        # Generate UUIDs for all tasks first
        task_ids = [uuid4() for _ in raw_tasks]

        tasks: list[AtomicTask] = []
        for i, raw in enumerate(raw_tasks):
            # Convert index-based dependencies to UUIDs
            dep_indices = raw.get("depends_on", [])
            dep_uuids = [task_ids[idx] for idx in dep_indices if idx < len(task_ids)]

            task = AtomicTask(
                task_id=task_ids[i],
                request_id=request.request_id,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                type=raw.get("type", "research.summarize"),
                params=raw.get("params", {}),
                priority=request.priority,
                dependencies=dep_uuids,
            )
            tasks.append(task)

        logger.info(
            "Decomposed request %s into %d tasks: %s",
            request.request_id,
            len(tasks),
            [t.type for t in tasks],
        )
        return tasks

    def _fallback_single_task(self, request: TaskRequest) -> list[AtomicTask]:
        """Create a single task when decomposition fails."""
        return [
            AtomicTask(
                request_id=request.request_id,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                type=request.intent,
                params=request.params,
                priority=request.priority,
            )
        ]
