"""End-to-end test: submit a task via HTTP API and verify it flows through the pipeline.

Requires: ./scripts/start.sh (Supervisor + workers + Redis + PostgreSQL all running)

This test submits a real task, waits for the Supervisor to decompose it,
workers to execute it, and verifies the final status.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e

SUPERVISOR_URL = "http://localhost:8100"


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(base_url=SUPERVISOR_URL, timeout=30.0)


class TestTaskFlowE2E:
    """End-to-end test for the full task lifecycle."""

    def test_health_check(self, client: httpx.Client) -> None:
        """Verify the Supervisor is running and healthy."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")

    def test_submit_and_complete_research_task(
        self, client: httpx.Client
    ) -> None:
        """Submit a research task and poll until completion.

        This exercises the full pipeline:
        1. POST /tasks → Supervisor accepts
        2. Supervisor decomposes (via Opus/LiteLLM)
        3. Research Worker executes (via Haiku/Sonnet/Opus)
        4. Results flow back through event bus
        5. GET /tasks/{id} shows COMPLETED
        """
        # Submit
        resp = client.post("/tasks", json={
            "user_id": "e2e-test-user",
            "conversation_id": "e2e-conv-1",
            "intent": "research.summarize",
            "raw_message": "Summarize the concept of event-driven architecture in 2 sentences",
            "params": {},
            "priority": "normal",
        })
        assert resp.status_code == 202
        request_id = resp.json()["request_id"]

        # Poll for completion (max 60 seconds)
        for _ in range(30):
            status_resp = client.get(f"/tasks/{request_id}")
            assert status_resp.status_code == 200
            data = status_resp.json()

            if data["status"] in ("COMPLETED", "FAILED"):
                break

            import time
            time.sleep(2)
        else:
            pytest.fail(
                f"Task {request_id} did not complete within 60 seconds. "
                f"Last status: {data['status']}"
            )

        # Verify
        assert data["status"] == "COMPLETED", (
            f"Task failed: {data.get('tasks', [])}"
        )
        assert len(data["tasks"]) >= 1

        # At least one sub-task should be COMPLETED
        completed_tasks = [
            t for t in data["tasks"] if t["status"] == "COMPLETED"
        ]
        assert len(completed_tasks) >= 1
        assert completed_tasks[0]["output"] is not None

    def test_submit_email_task(self, client: httpx.Client) -> None:
        """Submit an email draft task and verify completion."""
        resp = client.post("/tasks", json={
            "user_id": "e2e-test-user",
            "conversation_id": "e2e-conv-2",
            "intent": "email.draft",
            "raw_message": "Draft a short thank you email to the team",
            "params": {"to": "team@example.com", "subject": "Thank you"},
            "priority": "normal",
        })
        assert resp.status_code == 202
        request_id = resp.json()["request_id"]

        # Poll
        for _ in range(30):
            status_resp = client.get(f"/tasks/{request_id}")
            data = status_resp.json()
            if data["status"] in ("COMPLETED", "FAILED"):
                break
            import time
            time.sleep(2)

        assert data["status"] == "COMPLETED"

    def test_unknown_request_returns_404(self, client: httpx.Client) -> None:
        """GET a nonexistent request_id returns 404."""
        resp = client.get("/tasks/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
