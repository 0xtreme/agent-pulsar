"""Generic cold-tier container entrypoint.

Reads AP_TASK_JSON from environment, instantiates the appropriate worker,
executes the task, and prints the JSON TaskResult to stdout.

Usage (inside Docker container):
    python -m agent_pulsar.workers.cold_entrypoint
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time

from litellm import Router as LiteLLMRouter  # type: ignore[attr-defined]

from agent_pulsar.schemas.enums import ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import AtomicTask, TaskResult
from agent_pulsar.security.credential_provider import TokenBrokerCredentialProvider
from agent_pulsar.workers.base import ExecutionContext, SkillWorker

logger = logging.getLogger(__name__)


def _get_worker(skill_type: str) -> SkillWorker:
    """Get the worker instance for the given skill type.

    Import is deferred to avoid pulling in all workers unnecessarily.
    """
    from agent_pulsar.workers.payroll_worker import PayrollWorker

    workers = {
        "payroll": PayrollWorker,
    }

    worker_cls = workers.get(skill_type)
    if worker_cls is None:
        raise ValueError(f"Unknown cold-tier worker type: {skill_type}")
    return worker_cls()


async def _run() -> None:
    task_json = os.environ.get("AP_TASK_JSON")
    if not task_json:
        print(json.dumps({"error": "AP_TASK_JSON not set"}), file=sys.stderr)  # noqa: T201
        sys.exit(1)

    token_broker_url = os.environ.get("AP_TOKEN_BROKER_URL", "http://localhost:8101")
    model = os.environ.get("AP_MODEL", "claude-opus-4-0-20250514")

    task = AtomicTask.model_validate_json(task_json)

    worker = _get_worker(task.type.split(".")[0])

    # Build credential provider
    credential_provider = None
    if task.credential_ref:
        credential_provider = TokenBrokerCredentialProvider(
            user_id=task.request_id.hex[:16],
            broker_url=token_broker_url,
        )

    # Build a minimal LiteLLM router
    router = LiteLLMRouter(
        model_list=[{
            "model_name": model,
            "litellm_params": {"model": model},
        }]
    )

    context = ExecutionContext(
        task=task,
        litellm_router=router,
        model=model,
        credential_provider=credential_provider,
    )

    start = time.monotonic()
    try:
        result = await worker.execute(context)

        if credential_provider:
            await credential_provider.release_credentials()
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        result = TaskResult(
            task_id=task.task_id,
            request_id=task.request_id,
            status=TaskStatus.FAILED,
            error=str(e),
            model_used=model,
            execution_tier_used=ExecutionTier.COLD,
            duration_ms=elapsed,
        )

    # Print JSON result to stdout (this is how the runner collects it)
    print(result.model_dump_json())  # noqa: T201


def main() -> None:
    """Entry point for cold-tier containers."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
