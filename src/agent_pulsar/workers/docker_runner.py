"""Docker-based cold tier execution for sensitive tasks.

Spins up an isolated Docker container per-task, passes the AtomicTask as JSON
via environment variable, and collects the TaskResult from stdout.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from agent_pulsar.schemas.events import AtomicTask, TaskResult

logger = logging.getLogger(__name__)


class DockerRunnerError(Exception):
    """Error during Docker container execution."""


class DockerTaskRunner:
    """Runs a worker task inside an isolated Docker container."""

    def __init__(
        self,
        *,
        docker_network: str = "agent-pulsar-net",
        mem_limit: str = "512m",
        cpu_quota: int = 50000,
    ) -> None:
        self._docker_network = docker_network
        self._mem_limit = mem_limit
        self._cpu_quota = cpu_quota
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init Docker client."""
        if self._client is None:
            import docker

            self._client = docker.from_env()  # type: ignore[attr-defined]
        return self._client

    async def run_in_container(
        self,
        image: str,
        task: AtomicTask,
        token_broker_url: str,
        timeout_seconds: int = 300,
    ) -> TaskResult:
        """Run a task in a Docker container and return the result.

        The container receives the task as JSON in AP_TASK_JSON env var.
        It must print a JSON TaskResult to stdout and exit.
        """
        import asyncio

        task_json = task.model_dump_json()

        env = {
            "AP_TASK_JSON": task_json,
            "AP_TOKEN_BROKER_URL": token_broker_url,
            "AP_MODEL": task.model_assignment,
        }

        logger.info(
            "Starting cold-tier container for task %s (image=%s)",
            task.task_id, image,
        )

        def _run() -> str:
            client = self._get_client()

            container = client.containers.run(
                image=image,
                environment=env,
                detach=True,
                read_only=True,
                mem_limit=self._mem_limit,
                cpu_quota=self._cpu_quota,
                network=self._docker_network,
                remove=False,  # We remove after reading logs
            )

            try:
                wait_resp = container.wait(timeout=timeout_seconds)
                exit_code = wait_resp.get("StatusCode", -1)
                stdout = container.logs(stdout=True, stderr=False).decode("utf-8")
                stderr = container.logs(stdout=False, stderr=True).decode("utf-8")

                if exit_code != 0:
                    raise DockerRunnerError(
                        f"Container exited with code {exit_code}. "
                        f"stderr: {stderr[:500]}"
                    )

                output: str = stdout.strip()
                return output
            finally:
                with contextlib.suppress(Exception):
                    container.remove(force=True)

        try:
            stdout = await asyncio.to_thread(_run)
        except DockerRunnerError:
            raise
        except Exception as e:
            raise DockerRunnerError(f"Container execution failed: {e}") from e

        # Parse the JSON result from stdout
        try:
            result_data = json.loads(stdout)
            return TaskResult.model_validate(result_data)
        except (json.JSONDecodeError, ValueError) as e:
            raise DockerRunnerError(
                f"Failed to parse container output as TaskResult: {e}. "
                f"stdout: {stdout[:500]}"
            ) from e
