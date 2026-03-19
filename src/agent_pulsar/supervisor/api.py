"""Supervisor HTTP API routes.

POST /tasks  — Submit a task from the OpenClaw skill (202 Accepted)
GET  /tasks/{request_id} — Get status of a request and all sub-tasks
GET  /health — Liveness/readiness probe
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from agent_pulsar.schemas.enums import TaskStatus
from agent_pulsar.schemas.events import TaskRequest

router = APIRouter()


@router.post("/tasks", status_code=202)
async def submit_task(task_request: TaskRequest, request: Request) -> dict[str, Any]:
    """Accept a task from the OpenClaw skill.

    Publishes to the event bus for async processing. Returns immediately
    with the request_id for polling.
    """
    event_bus = request.app.state.event_bus
    await event_bus.publish("task.submitted", task_request)

    return {
        "request_id": str(task_request.request_id),
        "status": "accepted",
        "message": "Task submitted for processing.",
    }


@router.get("/tasks/{request_id}")
async def get_task_status(request_id: UUID, request: Request) -> dict[str, Any]:
    """Get the current status of a request and all its sub-tasks."""
    repo = request.app.state.repository

    req_record = await repo.get_request(request_id)
    if not req_record:
        raise HTTPException(status_code=404, detail="Request not found")

    task_records = await repo.get_tasks_for_request(request_id)

    return {
        "request_id": str(request_id),
        "status": req_record.status,
        "intent": req_record.intent,
        "created_at": req_record.created_at.isoformat() if req_record.created_at else None,
        "completed_at": (
            req_record.completed_at.isoformat() if req_record.completed_at else None
        ),
        "tasks": [
            {
                "task_id": str(t.task_id),
                "type": t.type,
                "status": t.status,
                "execution_tier": t.execution_tier,
                "model_assignment": t.model_assignment,
                "duration_ms": t.duration_ms,
                "error": t.error,
                "output": t.output,
            }
            for t in task_records
        ],
    }


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Liveness/readiness probe. Checks Redis and DB connectivity."""
    checks: dict[str, str] = {}

    # Check Redis
    try:
        event_bus = request.app.state.event_bus
        await event_bus.redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Check PostgreSQL
    try:
        engine = request.app.state.engine
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")  # type: ignore[arg-type]
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "checks": checks,
    }
