# Agent Pulsar -- Event Bus Message Schemas

> Version: 0.1.0 | Last updated: 2026-03-19
> Source of truth: `src/agent_pulsar/schemas/events.py` and `src/agent_pulsar/schemas/enums.py`

All inter-component communication in Agent Pulsar flows through the event bus. This document defines every topic, its Pydantic schema, consumer group assignments, and lifecycle semantics.

---

## Topics Overview

| Topic | Purpose | Type | Publisher | Consumer Group |
|-------|---------|------|-----------|----------------|
| `task.submitted` | New high-level task from OpenClaw skill | Standard | OpenClaw Skill | `agent-pulsar-supervisor` |
| `task.backlog.<skill>` | Decomposed atomic tasks partitioned by skill | Standard | Supervisor | `agent-pulsar-worker-<skill>` |
| `task.status` | Task status change notifications | Compacted | Supervisor, Workers | `agent-pulsar-supervisor`, `agent-pulsar-openclaw` |
| `task.results` | Completed task output from workers | Standard | Workers | `agent-pulsar-supervisor` |
| `task.completed` | Enriched completion event for user delivery | Standard | Supervisor | `agent-pulsar-openclaw` |
| `task.dlq` | Dead-letter queue for failed messages | Standard | Event Bus (auto) | Manual / ops tooling |

---

## Enumerations

These enums are shared across all message types. Defined in `src/agent_pulsar/schemas/enums.py`.

### TaskStatus

| Value | Description |
|-------|-------------|
| `PENDING` | Created, not yet dispatched to a worker |
| `CLAIMED` | Picked up by the Supervisor, being decomposed |
| `IN_PROGRESS` | Dispatched to a worker, currently executing |
| `COMPLETED` | Successfully finished |
| `FAILED` | Exhausted retries or hit a permanent failure |
| `DLQ` | Moved to the dead-letter queue |

### Priority

| Value | Description |
|-------|-------------|
| `normal` | Default priority |
| `high` | Elevated priority, dispatched before normal tasks |
| `critical` | Highest priority, preempts other tasks |

### ExecutionTier

| Value | Startup Latency | Isolation | Use Case |
|-------|----------------|-----------|----------|
| `hot` | ~100ms | Process-level | Email, calendar, quick lookups |
| `warm` | ~1-2s | Subprocess | Research, drafting, document processing |
| `cold` | ~5-10s | Docker container | Payroll, financial ops, sensitive data (Phase 2) |

### ComplexityTier

| Value | Model Class | Example Models |
|-------|-------------|----------------|
| `simple` | Fast/cheap | Claude Haiku 4.5, GPT-4o-mini |
| `moderate` | Balanced | Claude Sonnet 4.6, GPT-4o |
| `complex` | Max capability | Claude Opus 4.6 |

---

## Message Schemas

### 1. TaskRequest

**Topic**: `task.submitted`
**Publisher**: Agent Pulsar OpenClaw Skill
**Consumer**: Supervisor (`agent-pulsar-supervisor` group)
**Trigger**: User sends a message that the OpenClaw skill routes to Agent Pulsar

This is the high-level request before decomposition. The Supervisor will break it into atomic sub-tasks.

```python
class TaskRequest(BaseModel):
    request_id: UUID            # Auto-generated unique request identifier
    user_id: str                # User who submitted the request
    conversation_id: str        # OpenClaw conversation ID for result routing
    intent: str                 # Task intent (e.g., "payroll.run", "email.send")
    raw_message: str            # Original user message, verbatim
    params: dict[str, Any]      # Structured parameters extracted from the message
    priority: Priority          # normal | high | critical (default: normal)
    created_at: datetime        # ISO 8601 timestamp (default: now)
```

**Example JSON** (as serialized on the event bus):

```json
{
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "user-abc-123",
  "conversation_id": "openclaw-conv-456",
  "intent": "payroll.run",
  "raw_message": "Run payroll for March for all Easyrun employees",
  "params": {
    "company": "easyrun",
    "month": "2026-03"
  },
  "priority": "normal",
  "created_at": "2026-03-19T10:30:00Z"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `request_id` | UUID | No | auto-generated | Unique identifier for this request |
| `user_id` | string | Yes | -- | User identifier. Used for credential scoping (Phase 2) and multi-tenant isolation (Phase 4). |
| `conversation_id` | string | Yes | -- | Links back to the OpenClaw conversation so results reach the correct user/channel. |
| `intent` | string | Yes | -- | Determines decomposition strategy and worker routing. Format: `<domain>.<action>`. |
| `raw_message` | string | Yes | -- | Passed to the Task Decomposer (Opus) for context during decomposition. |
| `params` | object | No | `{}` | Pre-extracted parameters. Schema varies by intent. |
| `priority` | enum | No | `"normal"` | Affects dispatch ordering in the Supervisor. |
| `created_at` | datetime | No | now (UTC) | Event timestamp. |

---

### 2. AtomicTask

**Topic**: `task.backlog.<skill_type>` (e.g., `task.backlog.payroll`, `task.backlog.email`)
**Publisher**: Supervisor
**Consumer**: Skill Workers (`agent-pulsar-worker-<skill>` group)
**Trigger**: Supervisor decomposes a TaskRequest and dispatches ready sub-tasks

A single decomposed sub-task ready for worker execution. The topic is partitioned by skill type so each worker type only consumes tasks it can handle.

```python
class AtomicTask(BaseModel):
    task_id: UUID               # Auto-generated unique sub-task identifier
    request_id: UUID            # Links to parent TaskRequest
    user_id: str                # Propagated from parent request
    conversation_id: str        # Propagated from parent request
    type: str                   # Task type (e.g., "payroll.fetch_employees")
    params: dict[str, Any]      # Task-specific parameters
    priority: Priority          # Inherited from parent or overridden by Supervisor
    dependencies: list[UUID]    # Task IDs that must COMPLETE before this task starts
    credential_ref: str | None  # Vault secret reference (Phase 2), e.g., "vault:xero:easyrun"
    execution_tier: ExecutionTier  # hot | warm | cold
    model_assignment: str       # LLM model ID (e.g., "claude-haiku-4-5-20250414")
    created_at: datetime        # ISO 8601 timestamp
    timeout_ms: int             # Max execution time before self-termination (default: 300000)
    retry_policy: RetryPolicy   # Retry configuration
```

**RetryPolicy** (embedded):

```python
class RetryPolicy(BaseModel):
    max_retries: int    # Maximum retry attempts (default: 3)
    backoff: str        # "exponential" or "fixed" (default: "exponential")
    base_delay_ms: int  # Base delay in ms for backoff calculation (default: 1000)
```

**Example JSON**:

```json
{
  "task_id": "11111111-1111-1111-1111-111111111111",
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "user-abc-123",
  "conversation_id": "openclaw-conv-456",
  "type": "payroll.fetch_employees",
  "params": {
    "company": "easyrun",
    "month": "2026-03"
  },
  "priority": "normal",
  "dependencies": [],
  "credential_ref": "vault:xero:easyrun",
  "execution_tier": "cold",
  "model_assignment": "claude-opus-4-0-20250514",
  "created_at": "2026-03-19T10:30:01Z",
  "timeout_ms": 300000,
  "retry_policy": {
    "max_retries": 3,
    "backoff": "exponential",
    "base_delay_ms": 1000
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `task_id` | UUID | No | auto-generated | Unique sub-task identifier |
| `request_id` | UUID | Yes | -- | Links to the parent `TaskRequest` |
| `user_id` | string | Yes | -- | Propagated from parent for credential scoping |
| `conversation_id` | string | Yes | -- | Propagated from parent for result routing |
| `type` | string | Yes | -- | Determines which worker handles this task. Format: `<domain>.<operation>`. |
| `params` | object | No | `{}` | Worker-specific parameters |
| `priority` | enum | No | `"normal"` | Dispatch priority |
| `dependencies` | list[UUID] | No | `[]` | Tasks that must complete before dispatch. Empty = immediately ready. |
| `credential_ref` | string or null | No | `null` | Vault reference for credential access (Phase 2). Format: `vault:<service>:<scope>`. |
| `execution_tier` | enum | No | `"hot"` | Assigned by the Execution Tier Selector |
| `model_assignment` | string | No | `"claude-haiku-4-5-20250414"` | LLM model assigned by the Model Router |
| `created_at` | datetime | No | now (UTC) | Timestamp |
| `timeout_ms` | integer | No | `300000` (5 min) | Worker must complete within this window or self-terminate |
| `retry_policy` | RetryPolicy | No | `{max_retries: 3, backoff: "exponential", base_delay_ms: 1000}` | Retry behavior on failure |

---

### 3. TaskResult

**Topic**: `task.results`
**Publisher**: Skill Workers
**Consumer**: Supervisor (`agent-pulsar-supervisor` group)
**Trigger**: Worker completes (or fails) an AtomicTask

```python
class TaskResult(BaseModel):
    task_id: UUID                           # The AtomicTask that was executed
    request_id: UUID                        # Parent request
    status: TaskStatus                      # COMPLETED or FAILED
    output: dict[str, Any]                  # Task output (empty dict on failure)
    error: str | None                       # Error description (null on success)
    model_used: str | None                  # Actual model used (may differ from assignment due to fallback)
    execution_tier_used: ExecutionTier | None  # Actual tier used
    duration_ms: int                        # Execution wall time in milliseconds
    retry_count: int                        # How many retries were needed
    completed_at: datetime                  # Completion timestamp
```

**Example JSON** (success):

```json
{
  "task_id": "11111111-1111-1111-1111-111111111111",
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "COMPLETED",
  "output": {
    "employees": [
      {"name": "Alice", "id": "emp-001"},
      {"name": "Bob", "id": "emp-002"},
      {"name": "Carol", "id": "emp-003"},
      {"name": "Dave", "id": "emp-004"}
    ],
    "count": 4
  },
  "error": null,
  "model_used": "claude-opus-4-0-20250514",
  "execution_tier_used": "cold",
  "duration_ms": 3200,
  "retry_count": 0,
  "completed_at": "2026-03-19T10:30:04Z"
}
```

**Example JSON** (failure):

```json
{
  "task_id": "22222222-2222-2222-2222-222222222222",
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "FAILED",
  "output": {},
  "error": "Xero API returned 401 Unauthorized: token expired",
  "model_used": "claude-opus-4-0-20250514",
  "execution_tier_used": "cold",
  "duration_ms": 1500,
  "retry_count": 3,
  "completed_at": "2026-03-19T10:31:15Z"
}
```

---

### 4. TaskStatusUpdate

**Topic**: `task.status` (compacted -- latest status per task_id wins)
**Publisher**: Supervisor and Workers
**Consumer**: Supervisor (`agent-pulsar-supervisor`), OpenClaw Skill (`agent-pulsar-openclaw`)
**Trigger**: Any status transition (PENDING -> CLAIMED -> IN_PROGRESS -> COMPLETED/FAILED/DLQ)

Used for real-time status tracking. The OpenClaw skill subscribes to provide progress updates to the user.

```python
class TaskStatusUpdate(BaseModel):
    task_id: UUID           # The task whose status changed
    request_id: UUID        # Parent request
    status: TaskStatus      # New status
    updated_at: datetime    # When the transition happened
    retry_count: int        # Current retry count
    error: str | None       # Error details (only on FAILED transitions)
```

**Example JSON**:

```json
{
  "task_id": "11111111-1111-1111-1111-111111111111",
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "IN_PROGRESS",
  "updated_at": "2026-03-19T10:30:02Z",
  "retry_count": 0,
  "error": null
}
```

---

### 5. CompletionEvent

**Topic**: `task.completed`
**Publisher**: Supervisor (Completion Notifier sub-component)
**Consumer**: OpenClaw Skill (`agent-pulsar-openclaw` group)
**Trigger**: All atomic tasks for a request reach a terminal state (COMPLETED or FAILED)

This is the final message for a request. The OpenClaw skill uses it to deliver results to the user via their messaging channel.

```python
class CompletionEvent(BaseModel):
    request_id: UUID            # The completed request
    user_id: str                # User to notify
    conversation_id: str        # OpenClaw conversation for result routing
    status: TaskStatus          # COMPLETED (all succeeded) or FAILED (any failed)
    summary: str                # Human-readable summary generated by Haiku
    results: list[TaskResult]   # Per-task results
    total_cost_usd: float       # Total LLM cost across all sub-tasks
    total_duration_ms: int      # Wall time from first task start to last task end
    completed_at: datetime      # When the request reached terminal state
```

**Example JSON**:

```json
{
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "user-abc-123",
  "conversation_id": "openclaw-conv-456",
  "status": "COMPLETED",
  "summary": "March payroll completed for 4 employees at Easyrun. Total: $12,340. Payslips sent to all employees via email.",
  "results": [
    {
      "task_id": "11111111-1111-1111-1111-111111111111",
      "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "status": "COMPLETED",
      "output": {"employees": ["Alice", "Bob", "Carol", "Dave"], "count": 4},
      "error": null,
      "model_used": "claude-opus-4-0-20250514",
      "execution_tier_used": "cold",
      "duration_ms": 3200,
      "retry_count": 0,
      "completed_at": "2026-03-19T10:30:04Z"
    }
  ],
  "total_cost_usd": 0.15,
  "total_duration_ms": 45000,
  "completed_at": "2026-03-19T10:30:45Z"
}
```

---

### 6. DLQ Message

**Topic**: `task.dlq`
**Publisher**: Event bus (RedisStreamsBus.move_to_dlq / Kafka DLQ producer)
**Consumer**: Manual / ops tooling (no automated consumer)
**Trigger**: A message exhausts its `max_retries` on any topic

DLQ messages are not a Pydantic model -- they are a wrapper around the original failed message with error metadata.

**Structure**:

```json
{
  "original_topic": "task.backlog.payroll",
  "error": "Exhausted 3 retries",
  "data": {
    "...original message payload..."
  },
  "moved_at": "2026-03-19T10:35:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `original_topic` | string | The topic the message failed on |
| `error` | string | Why the message was moved to DLQ |
| `data` | object | The original message payload (TaskRequest, AtomicTask, etc.) |
| `moved_at` | string (ISO 8601) | When the message was moved to DLQ |

---

## Consumer Group Assignments

Consumer groups ensure each message is processed by exactly one consumer within a group, enabling horizontal scaling.

| Consumer Group | Component | Subscribed Topics |
|----------------|-----------|-------------------|
| `agent-pulsar-supervisor` | Supervisor | `task.submitted`, `task.results`, `task.status` |
| `agent-pulsar-worker-email` | Email Worker | `task.backlog.email` |
| `agent-pulsar-worker-research` | Research Worker | `task.backlog.research` |
| `agent-pulsar-worker-payroll` | Payroll Worker (Phase 2) | `task.backlog.payroll` |
| `agent-pulsar-worker-calendar` | Calendar Worker (Phase 2) | `task.backlog.calendar` |
| `agent-pulsar-worker-code` | Code Worker (Phase 2+) | `task.backlog.code` |
| `agent-pulsar-openclaw` | Agent Pulsar OpenClaw Skill | `task.completed`, `task.status` |

---

## Message Lifecycle Diagram

```
User sends message via Telegram/Slack/...
  |
  v
OpenClaw Skill evaluates routing decision
  |
  |--- Simple task --> OpenClaw native MCP execution (no event bus)
  |
  |--- Complex/sensitive task:
  v
[task.submitted] -----> Supervisor consumes
                           |
                           | Task Decomposer creates DAG of AtomicTasks
                           | Model Router assigns models
                           | Execution Tier Selector assigns tiers
                           | Persist all tasks to PostgreSQL
                           |
                           v
                   For each ready task (dependencies met):
                           |
                           v
                   [task.backlog.<skill>] -----> Worker consumes
                   [task.status: IN_PROGRESS]     |
                                                  | Worker executes task
                                                  | Emits heartbeats
                                                  |
                                        +---------+---------+
                                        |                   |
                                     Success             Failure
                                        |                   |
                                        v                   v
                                [task.results]       Retry? (count < max)
                                [task.status:          |         |
                                 COMPLETED]          Yes        No
                                        |             |         |
                                        |             v         v
                                        |        Re-publish  [task.dlq]
                                        |        on topic    [task.status:
                                        |                     DLQ]
                                        v
                                  Supervisor checks:
                                  All tasks terminal?
                                        |
                                  +-----+-----+
                                  |           |
                                  No         Yes
                                  |           |
                                  v           v
                            Dispatch    Completion Notifier
                            next ready  generates summary
                            tasks       (Haiku via LiteLLM)
                                              |
                                              v
                                      [task.completed]
                                              |
                                              v
                                      OpenClaw Skill
                                      delivers to user
```

---

## DLQ Flow and Retry Semantics

### Retry Strategy

When a worker fails to process a message:

1. The event bus `nack()` method is called with the current `retry_count` and `max_retries`.
2. If `retry_count < max_retries`:
   - Calculate delay: `2^retry_count + random(0, 0.5)` seconds (exponential backoff with jitter).
   - Re-publish the message to the same topic with `retry_count` incremented.
   - The message is picked up again by any available consumer in the group.
3. If `retry_count >= max_retries`:
   - The message is moved to `task.dlq`.
   - A `TaskStatusUpdate` with status `DLQ` is published to `task.status`.
   - The Supervisor marks the task as DLQ in PostgreSQL.

### Retry Timing

| Attempt | Delay (approx.) | Cumulative Wait |
|---------|-----------------|-----------------|
| 1st retry | ~1.0-1.5s | ~1.2s |
| 2nd retry | ~2.0-2.5s | ~3.4s |
| 3rd retry | ~4.0-4.5s | ~7.6s |
| DLQ | -- | after ~7.6s total |

### DLQ Recovery (Phase 3)

In Phase 1, DLQ messages are visible in Redis Streams for manual inspection. Phase 3 adds:

- Admin API to list and inspect DLQ messages
- Replay capability: re-publish a DLQ message to its original topic
- Alerting when DLQ depth exceeds a threshold

### Failure Classification

The Supervisor distinguishes between transient and permanent failures:

| Failure Type | Action | Example |
|-------------|--------|---------|
| **Transient** | Retry with backoff | Network timeout, rate limit, temporary API unavailability |
| **Capability** | Retry with escalated model (Phase 3) | Model produced incorrect output, insufficient reasoning |
| **Permanent** | Move to DLQ immediately (skip remaining retries) | Invalid credentials, missing required data, malformed task |

---

## Serialization

All messages are serialized using Pydantic's `model_dump_json()` and stored in a single `payload` field within the Redis Stream entry:

```
XADD task.submitted * payload '{"request_id": "...", "user_id": "...", ...}'
```

For Kafka (Phase 3), messages will use JSON serialization with Confluent Schema Registry for schema validation and evolution.
