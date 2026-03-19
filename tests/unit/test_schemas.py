"""Unit tests for Pydantic schemas — serialization round-trips and validation."""

from uuid import uuid4

from agent_pulsar.schemas import (
    AtomicTask,
    CompletionEvent,
    ComplexityTier,
    ExecutionTier,
    Priority,
    RetryPolicy,
    TaskRequest,
    TaskResult,
    TaskStatus,
    TaskStatusUpdate,
)


class TestEnums:
    def test_task_status_values(self) -> None:
        assert TaskStatus.PENDING == "PENDING"
        assert TaskStatus.COMPLETED == "COMPLETED"
        assert TaskStatus.DLQ == "DLQ"

    def test_priority_values(self) -> None:
        assert Priority.NORMAL == "normal"
        assert Priority.CRITICAL == "critical"

    def test_execution_tier_values(self) -> None:
        assert ExecutionTier.HOT == "hot"
        assert ExecutionTier.COLD == "cold"

    def test_complexity_tier_values(self) -> None:
        assert ComplexityTier.SIMPLE == "simple"
        assert ComplexityTier.COMPLEX == "complex"


class TestTaskRequest:
    def test_minimal_creation(self) -> None:
        req = TaskRequest(
            user_id="user-1",
            conversation_id="conv-1",
            intent="email.send",
            raw_message="Send an email to John",
        )
        assert req.user_id == "user-1"
        assert req.priority == Priority.NORMAL
        assert req.params == {}
        assert req.request_id is not None

    def test_json_round_trip(self) -> None:
        req = TaskRequest(
            user_id="user-1",
            conversation_id="conv-1",
            intent="research.summarize",
            raw_message="Research quantum computing",
            priority=Priority.HIGH,
            params={"topic": "quantum computing"},
        )
        json_str = req.model_dump_json()
        restored = TaskRequest.model_validate_json(json_str)
        assert restored.request_id == req.request_id
        assert restored.priority == Priority.HIGH
        assert restored.params["topic"] == "quantum computing"

    def test_is_frozen(self) -> None:
        req = TaskRequest(
            user_id="u", conversation_id="c", intent="i", raw_message="m"
        )
        try:
            req.user_id = "new"  # type: ignore[misc]
            assert False, "Should have raised"
        except Exception:
            pass  # Expected — model is frozen


class TestAtomicTask:
    def test_defaults(self) -> None:
        task = AtomicTask(
            request_id=uuid4(),
            user_id="user-1",
            conversation_id="conv-1",
            type="email.send",
        )
        assert task.execution_tier == ExecutionTier.HOT
        assert task.model_assignment == "claude-haiku-4-5-20250414"
        assert task.timeout_ms == 300_000
        assert task.retry_policy.max_retries == 3
        assert task.dependencies == []

    def test_with_dependencies(self) -> None:
        dep_id = uuid4()
        task = AtomicTask(
            request_id=uuid4(),
            user_id="u",
            conversation_id="c",
            type="research.analyze",
            dependencies=[dep_id],
            execution_tier=ExecutionTier.WARM,
            model_assignment="claude-sonnet-4-0-20250514",
        )
        assert dep_id in task.dependencies
        assert task.execution_tier == ExecutionTier.WARM

    def test_json_round_trip(self) -> None:
        task = AtomicTask(
            request_id=uuid4(),
            user_id="u",
            conversation_id="c",
            type="email.draft",
            params={"to": "john@example.com", "subject": "Hello"},
        )
        restored = AtomicTask.model_validate_json(task.model_dump_json())
        assert restored.task_id == task.task_id
        assert restored.params["to"] == "john@example.com"


class TestRetryPolicy:
    def test_defaults(self) -> None:
        policy = RetryPolicy()
        assert policy.max_retries == 3
        assert policy.backoff == "exponential"
        assert policy.base_delay_ms == 1000

    def test_custom(self) -> None:
        policy = RetryPolicy(max_retries=5, backoff="fixed", base_delay_ms=500)
        assert policy.max_retries == 5


class TestTaskResult:
    def test_success_result(self) -> None:
        result = TaskResult(
            task_id=uuid4(),
            request_id=uuid4(),
            status=TaskStatus.COMPLETED,
            output={"email_draft": "Hello John..."},
            model_used="claude-haiku-4-5-20250414",
            duration_ms=1200,
        )
        assert result.status == TaskStatus.COMPLETED
        assert result.error is None

    def test_failure_result(self) -> None:
        result = TaskResult(
            task_id=uuid4(),
            request_id=uuid4(),
            status=TaskStatus.FAILED,
            error="Connection timeout to external API",
            retry_count=3,
        )
        assert result.status == TaskStatus.FAILED
        assert result.retry_count == 3

    def test_json_round_trip(self) -> None:
        result = TaskResult(
            task_id=uuid4(),
            request_id=uuid4(),
            status=TaskStatus.COMPLETED,
            output={"data": [1, 2, 3]},
        )
        restored = TaskResult.model_validate_json(result.model_dump_json())
        assert restored.task_id == result.task_id
        assert restored.output["data"] == [1, 2, 3]


class TestTaskStatusUpdate:
    def test_creation(self) -> None:
        update = TaskStatusUpdate(
            task_id=uuid4(),
            request_id=uuid4(),
            status=TaskStatus.IN_PROGRESS,
        )
        assert update.retry_count == 0
        assert update.error is None


class TestCompletionEvent:
    def test_successful_completion(self) -> None:
        req_id = uuid4()
        results = [
            TaskResult(
                task_id=uuid4(),
                request_id=req_id,
                status=TaskStatus.COMPLETED,
                duration_ms=500,
            ),
            TaskResult(
                task_id=uuid4(),
                request_id=req_id,
                status=TaskStatus.COMPLETED,
                duration_ms=800,
            ),
        ]
        event = CompletionEvent(
            request_id=req_id,
            user_id="user-1",
            conversation_id="conv-1",
            status=TaskStatus.COMPLETED,
            summary="Both tasks completed successfully.",
            results=results,
            total_duration_ms=1300,
        )
        assert len(event.results) == 2
        assert event.status == TaskStatus.COMPLETED

    def test_json_round_trip(self) -> None:
        event = CompletionEvent(
            request_id=uuid4(),
            user_id="u",
            conversation_id="c",
            status=TaskStatus.COMPLETED,
            summary="Done.",
        )
        restored = CompletionEvent.model_validate_json(event.model_dump_json())
        assert restored.summary == "Done."
