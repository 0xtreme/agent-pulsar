"""Base worker interface and execution context.

Every skill worker implements SkillWorker. The WorkerRunner handles the
lifecycle (subscribe → deserialize → execute → publish result).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litellm import Router as LiteLLMRouter  # type: ignore[attr-defined]

    from agent_pulsar.schemas.enums import ComplexityTier, ExecutionTier
    from agent_pulsar.schemas.events import AtomicTask, TaskResult


@dataclass
class ExecutionContext:
    """Everything a worker needs to execute a single task.

    A fresh context is created per-task — no cross-task state leakage.
    """

    task: AtomicTask
    litellm_router: LiteLLMRouter
    model: str  # The assigned model for this task


class SkillWorker(ABC):
    """Base interface for all skill workers."""

    @abstractmethod
    def skill_type(self) -> str:
        """The task type prefix this worker handles (e.g., 'email')."""

    @abstractmethod
    async def execute(self, context: ExecutionContext) -> TaskResult:
        """Execute the task. Return a structured result.

        This is where the actual work happens. Each invocation gets a fresh
        ExecutionContext — no memory from previous tasks.
        """

    @abstractmethod
    def capability_requirement(self) -> ComplexityTier:
        """Minimum model capability for this worker's tasks."""

    @abstractmethod
    def default_execution_tier(self) -> ExecutionTier:
        """Default execution tier for this worker."""
