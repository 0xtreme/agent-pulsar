#!/usr/bin/env python3
"""CLI entry point for starting a worker process.

Usage:
    python scripts/run_worker.py email
    python scripts/run_worker.py research
"""

from __future__ import annotations

import asyncio
import logging
import sys

from litellm import Router as LiteLLMRouter  # type: ignore[attr-defined]

from agent_pulsar.config import get_settings
from agent_pulsar.event_bus.redis_streams import RedisStreamsBus
from agent_pulsar.workers.email_worker import EmailWorker
from agent_pulsar.workers.general_worker import GeneralWorker
from agent_pulsar.workers.research_worker import ResearchWorker
from agent_pulsar.workers.runner import WorkerRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

WORKERS = {
    "email": {
        "class": EmailWorker,
        "topic": "task.backlog.email",
    },
    "research": {
        "class": ResearchWorker,
        "topic": "task.backlog.research",
    },
    "general": {
        "class": GeneralWorker,
        "topic": "task.backlog.general",
    },
}


async def main(worker_type: str) -> None:
    if worker_type not in WORKERS:
        print(f"Unknown worker type: {worker_type}")
        print(f"Available workers: {', '.join(WORKERS.keys())}")
        sys.exit(1)

    settings = get_settings()
    worker_config = WORKERS[worker_type]

    # Create event bus
    event_bus = RedisStreamsBus(settings.redis_url, settings.event_bus_poll_ms)
    await event_bus.connect()

    # Create LiteLLM router
    litellm_router = LiteLLMRouter(
        model_list=[
            {
                "model_name": "claude-haiku-4-5-20250414",
                "litellm_params": {
                    "model": "claude-haiku-4-5-20250414",
                    "api_key": settings.anthropic_api_key,
                },
            },
            {
                "model_name": "claude-sonnet-4-0-20250514",
                "litellm_params": {
                    "model": "claude-sonnet-4-0-20250514",
                    "api_key": settings.anthropic_api_key,
                },
            },
            {
                "model_name": "claude-opus-4-0-20250514",
                "litellm_params": {
                    "model": "claude-opus-4-0-20250514",
                    "api_key": settings.anthropic_api_key,
                },
            },
        ],
        num_retries=2,
        timeout=120,
    )

    # Create worker
    worker = worker_config["class"]()
    runner = WorkerRunner(worker, event_bus, litellm_router)

    logger.info("Starting %s worker...", worker_type)

    try:
        await runner.run(worker_config["topic"])
    except KeyboardInterrupt:
        logger.info("Worker shutting down...")
    finally:
        await event_bus.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_worker.py <worker_type>")
        print(f"Available workers: {', '.join(WORKERS.keys())}")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
