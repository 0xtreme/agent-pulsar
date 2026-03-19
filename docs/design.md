# Agent Pulsar -- System Design Document

> Version: 0.1.0 | Last updated: 2026-03-19

---

## 1. Overview

Agent Pulsar is an event-driven AI agent orchestration framework that adds distributed systems reliability to personal AI. It sits behind OpenClaw (the user-facing chat layer) and provides task decomposition, credential isolation, dynamic model selection, and fault-tolerant execution through ephemeral workers.

The core insight: not every task needs orchestration. Simple, non-sensitive tasks (weather checks, basic calendar reads) stay in OpenClaw. Complex, sensitive, or multi-step tasks route through Agent Pulsar's isolated worker pipeline. This two-path design avoids unnecessary overhead while providing enterprise-grade reliability where it matters.

### 1.1 Design Philosophy

**Leverage, don't reinvent.** Agent Pulsar is an orchestration and isolation layer, not a full-stack framework. We use best-in-class open-source tools for capabilities that already exist and only build what is genuinely novel.

| Principle | Implication |
|-----------|-------------|
| Event-driven over request-response | All inter-component communication flows through the event bus |
| Ephemeral workers over persistent agents | Workers have zero cross-task memory; each task gets a fresh context |
| Credential isolation by default | Workers receive scoped, short-lived tokens; raw secrets never leave Vault |
| Cost-optimized model selection | Each task gets the cheapest model that can handle it, not a one-size-fits-all |
| Fail loudly, retry gracefully | DLQ for poison pills, exponential backoff for transient failures |

---

## 2. Architecture Diagram

Agent Pulsar is a 3-tier event-driven system with a central message bus:

```
 User (Telegram / WhatsApp / Slack / Discord / ...)
  |
  v
+------------------------------------------------------------------+
|  TIER 1 -- User Interface (LEVERAGED)                            |
|  OpenClaw (MIT) -- 20+ messaging channels                        |
|  Conversation management, skills system, MCP support             |
|                                                                  |
|  +---------------------------+                                   |
|  | Agent Pulsar OpenClaw     |  Routes complex/sensitive tasks   |
|  | Skill (BUILT)             |  to event bus; simple tasks stay  |
|  +------------+--------------+  in OpenClaw native execution     |
|               |                                                  |
+------------------------------------------------------------------+
                |
                |  publishes TaskRequest
                v
+------------------------------------------------------------------+
|  EVENT BUS -- Central Nervous System (BUILT)                     |
|  Redis Streams (dev) / Apache Kafka (prod)                       |
|                                                                  |
|  Topics:                                                         |
|    task.submitted        task.backlog.<skill>                    |
|    task.status           task.results                            |
|    task.completed        task.dlq                                |
+------------------------------------------------------------------+
       |                      ^                    ^
       | consumes             | publishes          | publishes
       v                      | TaskResult         | heartbeats
+------------------------------------------------------------------+
|  TIER 2 -- Control Plane (BUILT)                                 |
|  Supervisor Agent                                                |
|                                                                  |
|  +----------------+  +--------------+  +---------------------+   |
|  | Task           |  | Model        |  | Execution Tier      |   |
|  | Decomposer     |  | Router       |  | Selector            |   |
|  +----------------+  +--------------+  +---------------------+   |
|  +----------------+  +--------------+  +---------------------+   |
|  | Task Router    |  | Health       |  | Retry & DLQ         |   |
|  |                |  | Monitor      |  | Handler             |   |
|  +----------------+  +--------------+  +---------------------+   |
|  +---------------------+                                         |
|  | Completion Notifier  |                                        |
|  +---------------------+                                         |
|                                                                  |
|  HTTP API: POST /tasks, GET /tasks/{id}, GET /health             |
+------------------------------------------------------------------+
       |
       | dispatches AtomicTask to task.backlog.<skill>
       v
+------------------------------------------------------------------+
|  TIER 3 -- Execution Plane (BUILT)                               |
|  Skill Workers (Ephemeral)                                       |
|                                                                  |
|  +--------+  +----------+  +----------+  +----------+            |
|  | Email  |  | Research |  | Payroll  |  | Calendar |            |
|  | Worker |  | Worker   |  | Worker   |  | Worker   |  ...       |
|  | (hot)  |  | (warm)   |  | (cold)   |  | (hot)    |            |
|  +--------+  +----------+  +----------+  +----------+            |
|                                                                  |
|  Stateless | single-task | isolated | zero persistent context    |
|  Tools via MCP (leveraged)                                       |
+------------------------------------------------------------------+

Cross-cutting concerns:
  - Security Layer: HashiCorp Vault + Token Broker + Audit (BUILT)
  - LLM Gateway: LiteLLM (LEVERAGED)
  - Observability: OpenTelemetry + Langfuse (LEVERAGED, Phase 4)
  - Task State DB: PostgreSQL / Supabase (LEVERAGED)
  - Cache: Redis (LEVERAGED)
```

---

## 3. Component Responsibilities

| Component | Owner | Responsibility |
|-----------|-------|----------------|
| **OpenClaw** | Leveraged | User-facing chat across 20+ channels, conversation management, simple task execution via native MCP |
| **Agent Pulsar OpenClaw Skill** | Built | Bridges OpenClaw to the event bus; decides which tasks need orchestration vs. native execution |
| **Event Bus (Redis Streams / Kafka)** | Built (abstraction) | Durable, ordered message delivery with consumer groups, DLQ, and replay |
| **Supervisor** | Built | Task decomposition (DAG), model selection, execution tier assignment, health monitoring, retry/DLQ, result collection |
| **Task Decomposer** | Built (Supervisor sub-component) | Uses Claude Opus via LiteLLM to break complex requests into atomic sub-tasks with dependency ordering |
| **Model Router** | Built (Supervisor sub-component) | Classifies task complexity (simple/moderate/complex) and selects the cheapest capable model |
| **Execution Tier Selector** | Built (Supervisor sub-component) | Assigns hot/warm/cold execution based on security needs, latency, and compute requirements |
| **Skill Workers** | Built | Stateless, single-task executors; access tools via MCP; report results to event bus |
| **Token Broker** | Built (Phase 2) | Issues scoped, time-limited JWT tokens backed by Vault secrets |
| **Config Portal** | Built (Phase 2) | Minimal web UI for secure credential onboarding (OAuth flows + API key forms) |
| **LiteLLM** | Leveraged | Unified LLM gateway across Claude, GPT, Llama; retries, fallbacks, cost tracking |
| **HashiCorp Vault** | Leveraged (Phase 2) | Secrets vault; all user API keys encrypted at rest (AES-256-GCM) |
| **PostgreSQL** | Leveraged | Task state persistence (requests, atomic tasks, status, results) |
| **Redis** | Leveraged | Event bus transport (dev), cache, session state |

---

## 4. Data Flow Diagrams

### 4.1 Complex Task: "Run payroll for March for all Easyrun employees"

```
User (Telegram)
  |
  | "Run payroll for March for all Easyrun employees"
  v
OpenClaw
  |
  | Agent Pulsar skill detects: payroll = sensitive + multi-step
  | Route to Agent Pulsar
  v
Event Bus [task.submitted]
  |
  | TaskRequest { intent: "payroll.run", params: {company: "easyrun", month: "2026-03"} }
  v
Supervisor
  |
  | 1. Task Decomposer (Opus) creates DAG:
  |    fetch_employees --> calculate_payroll --> submit_payroll --> send_payslips
  |
  | 2. Model Router: complex --> Opus
  | 3. Execution Tier: sensitive financial data --> Cold (Docker)
  | 4. Persist to PostgreSQL
  v
Event Bus [task.backlog.payroll]
  |
  | AtomicTask { type: "payroll.fetch_employees" }  (first in chain)
  v
Payroll Worker (cold-tier Docker container)
  |
  | 1. Request scoped token from Token Broker (xero:payroll:write, TTL 5min)
  | 2. Execute via MCP --> Xero API
  | 3. Publish result to task.results
  | 4. Container terminates, token revoked
  v
Event Bus [task.results]
  |
  | TaskResult { status: COMPLETED, output: {employees: [...]} }
  v
Supervisor
  |
  | Dependencies met --> dispatch next task in chain
  | Repeat for calculate_payroll, submit_payroll, send_payslips
  |
  | All 4 tasks COMPLETED
  | Completion Notifier enriches with summary
  v
Event Bus [task.completed]
  |
  | CompletionEvent { summary: "March payroll completed for 4 employees. Total: $12,340." }
  v
Agent Pulsar OpenClaw Skill
  |
  | Relays result via OpenClaw
  v
User (Telegram): "Done -- March payroll completed for 4 employees. Total: $12,340."
```

### 4.2 Simple Task: "What's on my calendar today?"

```
User (Telegram)
  |
  | "What's on my calendar today?"
  v
OpenClaw
  |
  | Agent Pulsar skill evaluates:
  |   - Single-step operation? YES
  |   - Non-sensitive read? YES
  |   - Needs Vault credentials? NO
  |
  | Decision: STAY IN OPENCLAW
  v
OpenClaw native MCP --> Google Calendar API
  |
  | Direct response, no event bus, no Supervisor, no worker
  v
User (Telegram): "You have 3 meetings today: ..."
```

This two-path routing is a key architectural decision. Overhead is proportional to task complexity.

---

## 5. Interface Contracts

### 5.1 Event Bus Topics

All inter-component communication flows through the event bus. Components never call each other directly (except the Supervisor HTTP API for external queries).

| Topic | Publisher | Consumer | Message Type | Purpose |
|-------|-----------|----------|--------------|---------|
| `task.submitted` | OpenClaw Skill | Supervisor | `TaskRequest` | New high-level task from user |
| `task.backlog.<skill>` | Supervisor | Skill Workers | `AtomicTask` | Decomposed sub-task for specific worker type |
| `task.status` | Supervisor, Workers | Supervisor, OpenClaw Skill | `TaskStatusUpdate` | Status change notifications (compacted) |
| `task.results` | Workers | Supervisor | `TaskResult` | Completed task output |
| `task.completed` | Supervisor | OpenClaw Skill | `CompletionEvent` | All sub-tasks done; enriched summary for user |
| `task.dlq` | Event Bus (auto) | Ops/Manual | DLQ wrapper | Failed messages after max retries |

### 5.2 Supervisor HTTP API

The Supervisor exposes an HTTP API (FastAPI) for task submission and status queries. This is primarily used by the OpenClaw skill and for debugging.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tasks` | POST | Submit a new task request |
| `/tasks/{request_id}` | GET | Get status of a request and all sub-tasks |
| `/health` | GET | Liveness/readiness probe (Redis + PostgreSQL connectivity) |

Full specification: [api-spec.md](api-spec.md)

### 5.3 OpenClaw Webhook Callback

The Agent Pulsar OpenClaw Skill registers a webhook with the Supervisor. When a `CompletionEvent` is published to `task.completed`, the skill delivers the result to the user via OpenClaw's messaging API.

- **Callback URL**: Configured via `AP_OPENCLAW_WEBHOOK_URL` (default: `http://localhost:18789/hooks/agent`)
- **Payload**: JSON-serialized `CompletionEvent`
- **Method**: POST

### 5.4 Worker Plugin Interface

All workers implement the `SkillWorker` abstract base class:

```python
class SkillWorker(ABC):
    @abstractmethod
    def skill_type(self) -> str: ...

    @abstractmethod
    async def execute(self, task: Task, context: ExecutionContext) -> TaskResult: ...

    @abstractmethod
    def capability_requirement(self) -> CapabilityRequirement: ...

    @abstractmethod
    def default_execution_tier(self) -> ExecutionTier: ...
```

### 5.5 Token Broker API (Phase 2)

Workers request scoped credentials from the Token Broker:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tokens/issue` | POST | Issue a scoped JWT backed by a Vault secret |
| `/tokens/revoke` | POST | Revoke a token on task completion |

---

## 6. Phase 1 Scope Boundary

Phase 1 proves the core decomposition-to-execution loop end to end.

### Included in Phase 1

- OpenClaw deployment with Telegram channel
- Agent Pulsar OpenClaw skill (bridge to event bus)
- Redis Streams as event bus
- Supervisor with task decomposition (Opus via LiteLLM)
- Basic Model Router (simple/moderate/complex classification via Haiku)
- PostgreSQL for task state persistence
- 2 skill workers: Email Worker (hot tier) + Research Worker (warm tier)
- In-process (hot) and subprocess (warm) execution tiers
- Routing logic: simple tasks stay in OpenClaw, complex tasks route to Agent Pulsar
- Supervisor HTTP API (POST /tasks, GET /tasks/{id}, GET /health)
- DLQ for failed messages (basic -- full retry logic in Phase 3)

### NOT Included in Phase 1

- HashiCorp Vault / Token Broker / credential isolation (Phase 2)
- Config Portal for credential onboarding (Phase 2)
- Cold tier / Docker container execution (Phase 2)
- Payroll Worker, Calendar Worker (Phase 2)
- Kafka migration (Phase 3)
- Schema Registry (Phase 3)
- Kubernetes deployment (Phase 3)
- Full DLQ replay and advanced retry logic (Phase 3)
- Observability stack: OpenTelemetry, Langfuse, Prometheus, Grafana (Phase 4)
- Multi-tenant support (Phase 4)
- Plugin SDK for third-party workers (Phase 4)
- Advanced memory (Letta or vector store) (Phase 3+)

### Phase 1 Deliverable

User sends "research X and email me a summary" via Telegram. OpenClaw receives the message. Agent Pulsar decomposes into research + email tasks. Workers execute in sequence. Result returned to user via Telegram.

---

## 7. Key Design Decisions

### 7.1 OpenClaw as the PA Layer

**Decision**: Use OpenClaw for all user-facing chat instead of building our own.

**Rationale**: OpenClaw provides 20+ messaging channel adapters, conversation management, a skills system, native MCP support, and a web-based admin UI -- all MIT licensed. Building even a fraction of this would take months and add no differentiated value. Agent Pulsar's value is in orchestration, not chat.

### 7.2 Event-Driven Over Request-Response

**Decision**: All communication between the OpenClaw skill, Supervisor, and Workers flows through the event bus. No direct HTTP calls between components (except the Supervisor's query API).

**Rationale**: Event-driven architecture provides natural decoupling, replay capability, DLQ for failures, and the ability to swap transports (Redis Streams for dev, Kafka for prod) without changing application code.

### 7.3 Redis Streams for Dev, Kafka for Prod

**Decision**: Use Redis Streams in development (Phase 1-2) and migrate to Kafka in production (Phase 3).

**Rationale**: Redis is already needed for caching and session state -- one dependency, two uses. Redis Streams provides consumer groups and ordered delivery, which is sufficient for single-node dev. Kafka adds durability, partitioning, and replay at scale. The `EventBus` abstraction layer makes the swap transparent.

### 7.4 Ephemeral Workers with Zero Cross-Task Memory

**Decision**: Workers are stateless. Each task gets a fresh LLM context window. No shared memory between tasks.

**Rationale**: This eliminates context bleed (a hallucination source in other frameworks), provides natural credential isolation (tokens scoped to one task), and simplifies scaling (workers are interchangeable).

### 7.5 Three Execution Tiers

**Decision**: Hot (in-process, ~100ms), Warm (subprocess, ~1-2s), Cold (Docker, ~5-10s).

**Rationale**: Not every task needs a Docker container. Email sends need sub-second latency. Payroll needs full container isolation. The tier system lets the Supervisor optimize for both latency and security on a per-task basis.

### 7.6 Dynamic Model Selection

**Decision**: The Model Router classifies task complexity and assigns the cheapest model that can handle it.

**Rationale**: Using Opus for every task wastes money. Using Haiku for every task reduces quality. The Model Router (itself running on Haiku for cost) evaluates each task and routes to the right tier: Haiku for simple lookups, Sonnet for moderate tasks, Opus for complex reasoning.

### 7.7 Task Decomposition as a DAG

**Decision**: The Supervisor decomposes complex requests into a directed acyclic graph (DAG) of atomic sub-tasks with explicit dependencies.

**Rationale**: DAG-based decomposition enables parallel execution of independent sub-tasks while respecting ordering constraints. A payroll task naturally forms a chain (fetch employees, calculate, submit, send payslips), while a research task might have parallel branches that merge at the end.

### 7.8 LiteLLM as the LLM Gateway

**Decision**: All LLM calls (Supervisor, Model Router, Workers) route through LiteLLM.

**Rationale**: LiteLLM provides a unified API across Claude, GPT, Llama, and other providers. It handles retries, fallbacks, load balancing, and cost tracking. This means Agent Pulsar can swap models or providers without changing application code.

---

## 8. Technology Stack Summary

| Layer | Technology | License | Phase |
|-------|-----------|---------|-------|
| Chat Interface | OpenClaw | MIT | 1 |
| Admin UI | OpenClaw Control UI | MIT | 1 |
| Event Bus (dev) | Redis Streams | BSD-3 | 1 |
| Event Bus (prod) | Apache Kafka | Apache 2.0 | 3 |
| Task State DB | PostgreSQL (Supabase) | PostgreSQL License | 1 |
| LLM Gateway | LiteLLM | MIT | 1 |
| Tool Connectivity | MCP | Open standard | 1 |
| Secrets Vault | HashiCorp Vault | BSL 1.1 | 2 |
| Cache | Redis | BSD-3 | 1 |
| Container Runtime | Docker | Apache 2.0 | 2 |
| Observability | OpenTelemetry + Langfuse | Apache 2.0 / MIT | 4 |
| Language | Python 3.12+ | -- | 1 |
| Web Framework | FastAPI | MIT | 1 |
