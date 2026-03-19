"""Unit tests for DockerTaskRunner (with mock Docker client)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from agent_pulsar.schemas.enums import ExecutionTier, TaskStatus
from agent_pulsar.schemas.events import AtomicTask, TaskResult
from agent_pulsar.workers.docker_runner import DockerRunnerError, DockerTaskRunner


def _make_task(**overrides: object) -> AtomicTask:
    defaults = {
        "task_id": uuid4(),
        "request_id": uuid4(),
        "user_id": "test-user",
        "conversation_id": "test-conv",
        "type": "payroll.run",
        "params": {},
        "execution_tier": ExecutionTier.COLD,
        "model_assignment": "claude-opus-4-0-20250514",
    }
    defaults.update(overrides)
    return AtomicTask(**defaults)  # type: ignore[arg-type]


def _make_result(task: AtomicTask) -> TaskResult:
    return TaskResult(
        task_id=task.task_id,
        request_id=task.request_id,
        status=TaskStatus.COMPLETED,
        output={"total": 12340},
        model_used="claude-opus-4-0-20250514",
        execution_tier_used=ExecutionTier.COLD,
        duration_ms=5000,
    )


class TestDockerTaskRunner:
    """Tests for cold-tier Docker execution."""

    async def test_run_in_container_success(self) -> None:
        task = _make_task()
        expected_result = _make_result(task)

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [
            expected_result.model_dump_json().encode("utf-8"),  # stdout
            b"",  # stderr
        ]

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        runner = DockerTaskRunner()
        runner._client = mock_client

        result = await runner.run_in_container(
            image="agent-pulsar-payroll:latest",
            task=task,
            token_broker_url="http://localhost:8101",
        )

        assert result.status == TaskStatus.COMPLETED
        assert result.task_id == task.task_id
        assert result.output == {"total": 12340}

        # Verify container was run with correct env vars
        call_kwargs = mock_client.containers.run.call_args
        env = call_kwargs.kwargs["environment"]
        assert "AP_TASK_JSON" in env
        assert env["AP_TOKEN_BROKER_URL"] == "http://localhost:8101"
        assert env["AP_MODEL"] == "claude-opus-4-0-20250514"

        # Verify security constraints
        assert call_kwargs.kwargs["read_only"] is True
        assert call_kwargs.kwargs["mem_limit"] == "512m"

    async def test_run_in_container_nonzero_exit(self) -> None:
        task = _make_task()

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 1}
        mock_container.logs.side_effect = [
            b"",  # stdout
            b"Error: something went wrong",  # stderr
        ]

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        runner = DockerTaskRunner()
        runner._client = mock_client

        with pytest.raises(DockerRunnerError, match="exited with code 1"):
            await runner.run_in_container(
                image="test:latest",
                task=task,
                token_broker_url="http://localhost:8101",
            )

    async def test_run_in_container_invalid_json(self) -> None:
        task = _make_task()

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [
            b"not valid json",  # stdout
            b"",  # stderr
        ]

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        runner = DockerTaskRunner()
        runner._client = mock_client

        with pytest.raises(DockerRunnerError, match="Failed to parse"):
            await runner.run_in_container(
                image="test:latest",
                task=task,
                token_broker_url="http://localhost:8101",
            )

    async def test_container_cleaned_up_on_success(self) -> None:
        task = _make_task()
        result = _make_result(task)

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [
            result.model_dump_json().encode("utf-8"),
            b"",
        ]

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        runner = DockerTaskRunner()
        runner._client = mock_client

        await runner.run_in_container(
            image="test:latest",
            task=task,
            token_broker_url="http://localhost:8101",
        )

        mock_container.remove.assert_called_once_with(force=True)
