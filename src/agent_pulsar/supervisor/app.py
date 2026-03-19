"""FastAPI application for the Agent Pulsar Supervisor.

Wires up all components and starts background event consumers.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from litellm import Router as LiteLLMRouter  # type: ignore[attr-defined]

from agent_pulsar.config import get_settings
from agent_pulsar.event_bus.redis_streams import RedisStreamsBus
from agent_pulsar.persistence.database import create_engine, create_session_factory
from agent_pulsar.persistence.repository import TaskRepository
from agent_pulsar.schemas.enums import TaskStatus
from agent_pulsar.schemas.events import TaskRequest, TaskResult
from agent_pulsar.supervisor.api import router as api_router
from agent_pulsar.supervisor.collector import ResultCollector
from agent_pulsar.supervisor.decomposer import TaskDecomposer
from agent_pulsar.supervisor.model_router import ModelRouter
from agent_pulsar.supervisor.registry import SkillRegistry, create_default_registry
from agent_pulsar.supervisor.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


def _create_litellm_router(api_key: str) -> LiteLLMRouter:
    """Create a LiteLLM Router with Claude models."""
    return LiteLLMRouter(
        model_list=[
            {
                "model_name": "claude-haiku-4-5-20250414",
                "litellm_params": {
                    "model": "claude-haiku-4-5-20250414",
                    "api_key": api_key,
                },
            },
            {
                "model_name": "claude-sonnet-4-0-20250514",
                "litellm_params": {
                    "model": "claude-sonnet-4-0-20250514",
                    "api_key": api_key,
                },
            },
            {
                "model_name": "claude-opus-4-0-20250514",
                "litellm_params": {
                    "model": "claude-opus-4-0-20250514",
                    "api_key": api_key,
                },
            },
        ],
        num_retries=2,
        timeout=120,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Application lifespan — startup and shutdown."""
    settings = get_settings()

    # --- Startup ---
    logger.info("Starting Agent Pulsar Supervisor...")

    # Event bus
    event_bus = RedisStreamsBus(settings.redis_url, settings.event_bus_poll_ms)
    await event_bus.connect()
    app.state.event_bus = event_bus

    # Database
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    repository = TaskRepository(session_factory)
    app.state.repository = repository

    # LiteLLM
    litellm_router = _create_litellm_router(settings.anthropic_api_key)

    # Components
    decomposer = TaskDecomposer(litellm_router, settings.decomposition_model)
    model_router = ModelRouter(litellm_router, settings.classification_model)
    registry = create_default_registry()
    scheduler = TaskScheduler(event_bus, repository, registry)
    collector = ResultCollector(
        event_bus, repository, litellm_router, settings.openclaw_webhook_url
    )

    # Store for access in handlers
    app.state.decomposer = decomposer
    app.state.model_router = model_router
    app.state.registry = registry
    app.state.scheduler = scheduler
    app.state.collector = collector

    # --- Background consumers ---
    consumer_tasks = [
        asyncio.create_task(
            _consume_submitted(
                event_bus, settings, decomposer, model_router,
                registry, repository, scheduler,
            ),
            name="consumer-task-submitted",
        ),
        asyncio.create_task(
            _consume_results(event_bus, settings, scheduler, collector),
            name="consumer-task-results",
        ),
    ]

    logger.info("Agent Pulsar Supervisor started. Listening for tasks...")

    yield

    # --- Shutdown ---
    logger.info("Shutting down Agent Pulsar Supervisor...")
    for task in consumer_tasks:
        task.cancel()
    await asyncio.gather(*consumer_tasks, return_exceptions=True)
    await event_bus.close()
    await engine.dispose()
    logger.info("Shutdown complete.")


async def _consume_submitted(
    event_bus: RedisStreamsBus,
    settings: Any,
    decomposer: TaskDecomposer,
    model_router: ModelRouter,
    registry: SkillRegistry,
    repository: TaskRepository,
    scheduler: TaskScheduler,
) -> None:
    """Background consumer for task.submitted — decompose, classify, persist, dispatch."""

    async def handler(msg_id: str, payload: dict[str, Any]) -> None:
        request = TaskRequest.model_validate(payload)
        logger.info("Processing request %s: %s", request.request_id, request.intent)

        # 1. Persist the request
        await repository.save_request(request)

        # 2. Decompose into atomic tasks
        tasks = await decomposer.decompose(request)

        # 3. Classify complexity and assign models
        for i, task in enumerate(tasks):
            entry = registry.lookup(task.type)
            min_cap = entry.min_capability if entry else None
            tier, model = await model_router.classify_and_assign(
                task.type, task.params, min_cap
            )
            # AtomicTask is frozen, so create a new one with updated fields
            tasks[i] = task.model_copy(
                update={
                    "model_assignment": model,
                    "execution_tier": entry.default_tier if entry else task.execution_tier,
                }
            )

        # 4. Persist atomic tasks
        await repository.save_atomic_tasks(tasks)

        # 5. Dispatch tasks with no dependencies
        dispatched = await scheduler.dispatch_ready_tasks(request.request_id)
        logger.info(
            "Request %s: %d tasks created, %d dispatched immediately",
            request.request_id,
            len(tasks),
            dispatched,
        )

    await event_bus.subscribe(
        topic="task.submitted",
        group=settings.consumer_group,
        consumer="supervisor-submitted",
        handler=handler,
    )


async def _consume_results(
    event_bus: RedisStreamsBus,
    settings: Any,
    scheduler: TaskScheduler,
    collector: ResultCollector,
) -> None:
    """Background consumer for task.results — update state, release deps, check completion."""

    async def handler(msg_id: str, payload: dict[str, Any]) -> None:
        result = TaskResult.model_validate(payload)
        logger.info(
            "Received result for task %s: %s", result.task_id, result.status.value
        )

        if result.status == TaskStatus.COMPLETED:
            await scheduler.on_task_completed(result)
        elif result.status == TaskStatus.FAILED:
            await scheduler.on_task_failed(result)

        # Check if request is fully complete
        await collector.handle_result(result)

    await event_bus.subscribe(
        topic="task.results",
        group=settings.consumer_group,
        consumer="supervisor-results",
        handler=handler,
    )


# --- Create the app ---
app = FastAPI(
    title="Agent Pulsar Supervisor",
    description="Event-driven AI agent orchestration control plane",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router)
