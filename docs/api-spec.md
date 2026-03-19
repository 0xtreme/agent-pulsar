# Agent Pulsar -- Supervisor HTTP API Specification

> Version: 0.2.0 | Last updated: 2026-03-19
> Base URL: `http://localhost:8100` (configurable via `AP_SUPERVISOR_HOST` / `AP_SUPERVISOR_PORT`)

---

## Authentication

| Phase | Mechanism | Details |
|-------|-----------|---------|
| Phase 1 | None | API is accessible without authentication. Intended for local development and the co-located OpenClaw skill only. |
| Phase 2 | API Key (planned) | The Agent Pulsar OpenClaw Skill will authenticate with a shared secret passed via the `Authorization: Bearer <api-key>` header. The key is stored in Vault and injected into the skill at startup. Token Broker and Config Portal are running but Supervisor auth is not yet enforced. |

---

## Endpoints

### POST /tasks

Submit a new task request for decomposition and execution.

The Supervisor persists the request, publishes it to the event bus, and returns immediately with a `202 Accepted`. Task execution is asynchronous -- poll `GET /tasks/{request_id}` for status or wait for the webhook callback.

#### Request

```
POST /tasks
Content-Type: application/json
```

**Request Body -- `TaskRequest`**:

```json
{
  "user_id": "user-abc-123",
  "conversation_id": "openclaw-conv-456",
  "intent": "payroll.run",
  "raw_message": "Run payroll for March for all Easyrun employees",
  "params": {
    "company": "easyrun",
    "month": "2026-03"
  },
  "priority": "normal"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `user_id` | string | Yes | -- | Unique identifier for the user. Used for credential scoping and multi-tenant isolation. |
| `conversation_id` | string | Yes | -- | OpenClaw conversation ID. Used to route results back to the correct chat session. |
| `intent` | string | Yes | -- | Task intent identifier (e.g., `payroll.run`, `email.send`, `research.summarize`). Determines how the Supervisor decomposes and routes the task. |
| `raw_message` | string | Yes | -- | The original user message, verbatim. Passed to the Task Decomposer for context. |
| `params` | object | No | `{}` | Structured parameters extracted from the user message. Schema varies by intent. |
| `priority` | string | No | `"normal"` | Priority level: `"normal"`, `"high"`, or `"critical"`. Higher priority tasks are dispatched first. |

#### Response -- 202 Accepted

```json
{
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "CLAIMED",
  "created_at": "2026-03-19T10:30:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | string (UUID) | Unique identifier assigned to this request. Use for status polling. |
| `status` | string | Initial status. Always `"CLAIMED"` on successful submission. |
| `created_at` | string (ISO 8601) | Timestamp when the request was created. |

#### Error Responses

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Invalid request body (missing required fields, bad types) | `ErrorResponse` |
| 422 | Validation error (unknown priority, malformed params) | `ErrorResponse` |
| 503 | Event bus or database unavailable | `ErrorResponse` |

---

### GET /tasks/{request_id}

Retrieve the current status of a task request and all of its decomposed sub-tasks.

#### Request

```
GET /tasks/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

| Parameter | Location | Type | Required | Description |
|-----------|----------|------|----------|-------------|
| `request_id` | path | string (UUID) | Yes | The request ID returned from `POST /tasks` |

#### Response -- 200 OK

```json
{
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "user-abc-123",
  "conversation_id": "openclaw-conv-456",
  "intent": "payroll.run",
  "status": "IN_PROGRESS",
  "priority": "normal",
  "created_at": "2026-03-19T10:30:00Z",
  "completed_at": null,
  "tasks": [
    {
      "task_id": "11111111-1111-1111-1111-111111111111",
      "type": "payroll.fetch_employees",
      "status": "COMPLETED",
      "execution_tier": "cold",
      "model_assignment": "claude-opus-4-0-20250514",
      "dependencies": [],
      "retry_count": 0,
      "output": {
        "employees": ["Alice", "Bob", "Carol", "Dave"],
        "count": 4
      },
      "error": null,
      "duration_ms": 3200,
      "created_at": "2026-03-19T10:30:01Z",
      "completed_at": "2026-03-19T10:30:04Z"
    },
    {
      "task_id": "22222222-2222-2222-2222-222222222222",
      "type": "payroll.calculate_payroll",
      "status": "IN_PROGRESS",
      "execution_tier": "cold",
      "model_assignment": "claude-opus-4-0-20250514",
      "dependencies": ["11111111-1111-1111-1111-111111111111"],
      "retry_count": 0,
      "output": null,
      "error": null,
      "duration_ms": null,
      "created_at": "2026-03-19T10:30:05Z",
      "completed_at": null
    },
    {
      "task_id": "33333333-3333-3333-3333-333333333333",
      "type": "payroll.submit_payroll",
      "status": "PENDING",
      "execution_tier": "cold",
      "model_assignment": "claude-opus-4-0-20250514",
      "dependencies": ["22222222-2222-2222-2222-222222222222"],
      "retry_count": 0,
      "output": null,
      "error": null,
      "duration_ms": null,
      "created_at": "2026-03-19T10:30:05Z",
      "completed_at": null
    },
    {
      "task_id": "44444444-4444-4444-4444-444444444444",
      "type": "payroll.send_payslips",
      "status": "PENDING",
      "execution_tier": "cold",
      "model_assignment": "claude-opus-4-0-20250514",
      "dependencies": ["33333333-3333-3333-3333-333333333333"],
      "retry_count": 0,
      "output": null,
      "error": null,
      "duration_ms": null,
      "created_at": "2026-03-19T10:30:05Z",
      "completed_at": null
    }
  ]
}
```

**Top-level fields**:

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | string (UUID) | The request identifier |
| `user_id` | string | User who submitted the request |
| `conversation_id` | string | OpenClaw conversation ID for result routing |
| `intent` | string | Original task intent |
| `status` | string | Aggregate status: `PENDING`, `CLAIMED`, `IN_PROGRESS`, `COMPLETED`, `FAILED` |
| `priority` | string | Priority level |
| `created_at` | string (ISO 8601) | When the request was created |
| `completed_at` | string (ISO 8601) or null | When the request reached a terminal state, or null if still running |
| `tasks` | array | List of decomposed atomic sub-tasks (see below) |

**Per-task fields** (`tasks[]`):

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string (UUID) | Unique sub-task identifier |
| `type` | string | Task type (e.g., `payroll.fetch_employees`) |
| `status` | string | `PENDING`, `CLAIMED`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `DLQ` |
| `execution_tier` | string | `hot`, `warm`, or `cold` |
| `model_assignment` | string | LLM model assigned to this task |
| `dependencies` | array of UUID strings | Task IDs that must complete before this task can start |
| `retry_count` | integer | Number of retries attempted |
| `output` | object or null | Task output data on completion, null otherwise |
| `error` | string or null | Error description on failure, null otherwise |
| `duration_ms` | integer or null | Execution duration in milliseconds, null if not yet completed |
| `created_at` | string (ISO 8601) | When the sub-task was created |
| `completed_at` | string (ISO 8601) or null | When the sub-task completed, null if still running |

#### Error Responses

| Status | Condition | Body |
|--------|-----------|------|
| 404 | No request found with the given `request_id` | `ErrorResponse` |
| 503 | Database unavailable | `ErrorResponse` |

---

### GET /health

Liveness and readiness probe. Checks connectivity to Redis (event bus) and PostgreSQL (task state).

#### Request

```
GET /health
```

No parameters or body.

#### Response -- 200 OK (healthy)

```json
{
  "status": "healthy",
  "checks": {
    "redis": {
      "status": "up",
      "latency_ms": 1.2
    },
    "postgres": {
      "status": "up",
      "latency_ms": 3.5
    }
  },
  "version": "0.1.0"
}
```

#### Response -- 503 Service Unavailable (degraded)

```json
{
  "status": "degraded",
  "checks": {
    "redis": {
      "status": "up",
      "latency_ms": 1.1
    },
    "postgres": {
      "status": "down",
      "error": "connection refused"
    }
  },
  "version": "0.1.0"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"healthy"` if all checks pass, `"degraded"` if any check fails |
| `checks` | object | Per-dependency health status |
| `checks.<dep>.status` | string | `"up"` or `"down"` |
| `checks.<dep>.latency_ms` | number | Round-trip latency in milliseconds (omitted if down) |
| `checks.<dep>.error` | string | Error message (only present if down) |
| `version` | string | Agent Pulsar version from `pyproject.toml` |

---

## Error Response Format

All error responses use a consistent JSON structure:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Field 'user_id' is required",
    "details": {
      "field": "user_id",
      "type": "missing"
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `error.code` | string | Machine-readable error code (see table below) |
| `error.message` | string | Human-readable error description |
| `error.details` | object or null | Additional context (varies by error type) |

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Request body failed validation (missing fields, wrong types) |
| `INVALID_PRIORITY` | 422 | Priority value is not one of: `normal`, `high`, `critical` |
| `REQUEST_NOT_FOUND` | 404 | No task request exists with the given `request_id` |
| `EVENT_BUS_UNAVAILABLE` | 503 | Cannot connect to Redis / Kafka |
| `DATABASE_UNAVAILABLE` | 503 | Cannot connect to PostgreSQL |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

## Request / Response Schemas (JSON Schema)

### TaskSubmission (POST /tasks request body)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["user_id", "conversation_id", "intent", "raw_message"],
  "properties": {
    "user_id": {
      "type": "string",
      "minLength": 1,
      "description": "Unique user identifier"
    },
    "conversation_id": {
      "type": "string",
      "minLength": 1,
      "description": "OpenClaw conversation ID"
    },
    "intent": {
      "type": "string",
      "minLength": 1,
      "description": "Task intent (e.g., payroll.run, email.send)"
    },
    "raw_message": {
      "type": "string",
      "minLength": 1,
      "description": "Original user message verbatim"
    },
    "params": {
      "type": "object",
      "default": {},
      "description": "Structured parameters extracted from the message"
    },
    "priority": {
      "type": "string",
      "enum": ["normal", "high", "critical"],
      "default": "normal",
      "description": "Task priority level"
    }
  },
  "additionalProperties": false
}
```

### TaskSubmissionResponse (POST /tasks response)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["request_id", "status", "created_at"],
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "description": "Assigned request identifier"
    },
    "status": {
      "type": "string",
      "enum": ["CLAIMED"],
      "description": "Initial status (always CLAIMED)"
    },
    "created_at": {
      "type": "string",
      "format": "date-time",
      "description": "Creation timestamp (ISO 8601)"
    }
  }
}
```

### TaskStatusResponse (GET /tasks/{request_id} response)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["request_id", "user_id", "conversation_id", "intent", "status", "priority", "created_at", "tasks"],
  "properties": {
    "request_id": { "type": "string", "format": "uuid" },
    "user_id": { "type": "string" },
    "conversation_id": { "type": "string" },
    "intent": { "type": "string" },
    "status": {
      "type": "string",
      "enum": ["PENDING", "CLAIMED", "IN_PROGRESS", "COMPLETED", "FAILED"]
    },
    "priority": {
      "type": "string",
      "enum": ["normal", "high", "critical"]
    },
    "created_at": { "type": "string", "format": "date-time" },
    "completed_at": { "type": ["string", "null"], "format": "date-time" },
    "tasks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["task_id", "type", "status", "execution_tier", "model_assignment", "dependencies", "retry_count", "created_at"],
        "properties": {
          "task_id": { "type": "string", "format": "uuid" },
          "type": { "type": "string" },
          "status": {
            "type": "string",
            "enum": ["PENDING", "CLAIMED", "IN_PROGRESS", "COMPLETED", "FAILED", "DLQ"]
          },
          "execution_tier": {
            "type": "string",
            "enum": ["hot", "warm", "cold"]
          },
          "model_assignment": { "type": "string" },
          "dependencies": {
            "type": "array",
            "items": { "type": "string", "format": "uuid" }
          },
          "retry_count": { "type": "integer", "minimum": 0 },
          "output": { "type": ["object", "null"] },
          "error": { "type": ["string", "null"] },
          "duration_ms": { "type": ["integer", "null"] },
          "created_at": { "type": "string", "format": "date-time" },
          "completed_at": { "type": ["string", "null"], "format": "date-time" }
        }
      }
    }
  }
}
```

### HealthResponse (GET /health response)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["status", "checks", "version"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["healthy", "degraded"]
    },
    "checks": {
      "type": "object",
      "properties": {
        "redis": {
          "type": "object",
          "required": ["status"],
          "properties": {
            "status": { "type": "string", "enum": ["up", "down"] },
            "latency_ms": { "type": "number" },
            "error": { "type": "string" }
          }
        },
        "postgres": {
          "type": "object",
          "required": ["status"],
          "properties": {
            "status": { "type": "string", "enum": ["up", "down"] },
            "latency_ms": { "type": "number" },
            "error": { "type": "string" }
          }
        }
      }
    },
    "version": { "type": "string" }
  }
}
```

### ErrorResponse

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["error"],
  "properties": {
    "error": {
      "type": "object",
      "required": ["code", "message"],
      "properties": {
        "code": { "type": "string" },
        "message": { "type": "string" },
        "details": { "type": ["object", "null"] }
      }
    }
  }
}
```

---

## Phase 2 Services

### Token Broker API

> Base URL: `http://localhost:8101` (configurable via `AP_TOKEN_BROKER_HOST` / `AP_TOKEN_BROKER_PORT`)

The Token Broker issues scoped, short-lived JWT tokens backed by Vault secrets. Workers request tokens to access external API credentials.

#### POST /tokens/issue

Issue a scoped JWT token for a worker.

**Request Body:**

```json
{
  "user_id": "pavi",
  "credential_ref": "xero/payroll",
  "scope": "payroll:write",
  "ttl_seconds": 300
}
```

**Response -- 200 OK:**

```json
{
  "token": "eyJ...",
  "jti": "a1b2c3d4-...",
  "expires_at": "2026-03-19T15:35:00Z",
  "credential_data": {
    "api_key": "xk-...",
    "api_secret": "xs-..."
  }
}
```

**Error -- 400:** Credentials not found in Vault for the given user/ref.

#### POST /tokens/revoke

Revoke an active token by JTI.

**Request Body:** `{"jti": "a1b2c3d4-..."}`
**Response -- 200:** `{"status": "revoked"}`
**Error -- 404:** Token not found.

#### GET /health

**Response -- 200:** `{"status": "healthy", "active_tokens": 3}`

---

### Config Portal API

> Base URL: `http://localhost:8102` (configurable via `AP_CONFIG_PORTAL_HOST` / `AP_CONFIG_PORTAL_PORT`)

Secure credential onboarding for users. Generates one-time links, serves credential forms, stores secrets in Vault.

#### POST /api/links/generate

Generate a one-time onboarding link for a user + service.

**Request Body:** `{"user_id": "pavi", "service": "xero"}`
**Response -- 200:** `{"url": "http://localhost:8102/connect/<token>", "token": "...", "expires_in_seconds": 600}`

#### GET /connect/{token}

Render the credential submission form (HTML). Returns 400 if token is expired/invalid.

#### POST /connect/{token}

Submit credentials via form POST. Writes to Vault, invalidates the one-time token.

**Form fields:** `api_key` (required), `api_secret` (optional)

#### GET /api/connections/{user_id}

List connected services. **Response:** `[{"service": "xero", "connected": true}]`

#### DELETE /api/connections/{user_id}/{service}

Disconnect a service (deletes credentials from Vault). **Response:** `{"status": "disconnected"}`
