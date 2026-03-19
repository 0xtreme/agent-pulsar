# Agent Pulsar — Requirements & Architecture Specification

> Event-driven AI agent orchestration framework
> Version: 0.3 draft | Last updated: 2026-03-19

---

## 1. Problem Statement

Current AI agent frameworks (CrewAI, LangGraph, AutoGen, etc.) suffer from:

- **Context bleed**: Agents share memory across unrelated tasks, causing hallucinations and quality degradation as sessions grow
- **No credential isolation**: API keys stored in environment variables or in-process — one compromised agent exposes everything
- **No reliability primitives**: No message ordering, replay, dead-letter queues, or retry logic — tasks silently fail
- **Monolithic execution**: All agents run in the same process, so a hung payroll task blocks an email response
- **Static model assignment**: Every task uses the same model regardless of complexity, wasting cost on trivial operations

Agent Pulsar solves these by applying distributed systems principles (event-driven architecture, ephemeral workers, credential isolation, tiered execution) to personal AI.

### 1.1 Design Philosophy: Leverage, Don't Reinvent

Agent Pulsar is **not** a full-stack framework that rebuilds everything from scratch. It is an **orchestration and isolation layer** that leverages best-in-class open-source tools for capabilities that already exist. We only build what is genuinely novel.

### 1.2 Locked Technology Decisions

Every technology choice is **locked** with a clear rationale. No "or" options — one tool per job.

| Capability | Decision | Tool | License | Why This, Not Something Else |
|------------|----------|------|---------|------------------------------|
| User-facing chat agent | **Leverage** | OpenClaw | MIT | 20+ channels out of the box (Telegram, WhatsApp, Slack, Discord, Signal, etc.), skills system for extensibility, built-in MCP support, 214k+ stars, MIT license. No other tool matches this breadth. |
| User config & admin UI | **Leverage** | OpenClaw Control UI | MIT (part of OpenClaw) | OpenClaw ships a built-in web dashboard at `localhost:18789` with config management, session management, and auth. No need to build or add a separate admin panel. |
| Credential onboarding | **Build** (on top of OpenClaw) | Agent Pulsar Config Portal | — | OpenClaw stores keys in plaintext JSON files — not acceptable for sensitive credentials. We build a thin onboarding flow that routes credentials directly to Vault. See Section 9.5. |
| LLM gateway | **Leverage** | LiteLLM | MIT | Unified API across Claude, GPT, Llama, etc. Handles retries, fallbacks, load balancing, cost tracking. MIT license. The standard choice for multi-provider LLM routing. |
| Tool connectivity | **Leverage** | MCP | Open standard | Model Context Protocol is the emerging standard for LLM ↔ tool communication. OpenClaw supports it natively. Workers use it for all external API access. |
| Event bus (dev) | **Build** (abstraction) | Redis Streams | BSD-3 | Lightweight, already needed for caching. Good enough for dev/single-node. Our abstraction layer makes it swappable. |
| Event bus (prod) | **Build** (abstraction) | Apache Kafka (Confluent Cloud) | Apache 2.0 | Durable, ordered, replayable, partitioned. Enterprise-grade reliability. Confluent Cloud is managed — no ops overhead. |
| Task state DB | **Leverage** | PostgreSQL (Supabase) | PostgreSQL License | Supabase provides managed Postgres with auth, realtime, and edge functions. Free tier for dev. Standard choice. |
| Secrets vault | **Leverage** | HashiCorp Vault | BSL 1.1 | Industry standard for secrets management. BSL 1.1 allows all uses except offering a competing managed vault service. Self-hosted use in Agent Pulsar (even SaaS) is fine. |
| Cache | **Leverage** | Redis | BSD-3 | Already needed for event bus (dev) and session state. One dependency, two uses. |
| Container runtime | **Leverage** | Docker | Apache 2.0 | Standard. Cold-tier workers run in Docker containers. |
| Container orchestrator (prod) | **Leverage** | Kubernetes | Apache 2.0 | Standard for production container orchestration. Azure Container Apps as managed alternative. |
| Observability — tracing | **Leverage** | OpenTelemetry + Langfuse | Apache 2.0 / MIT | OpenTelemetry is the standard for distributed tracing. Langfuse adds LLM-specific observability (cost, latency, token usage). |
| Observability — metrics | **Leverage** | Prometheus + Grafana | Apache 2.0 | Standard metrics/dashboarding stack. |
| Language | **Build** | Python 3.12+ | — | Best LLM ecosystem (Anthropic SDK, LiteLLM, MCP SDK all Python-first). AsyncIO for concurrency. |
| Async framework | **Build** | FastAPI | MIT | Standard Python async web framework. Handles Supervisor API, Token Broker API, health endpoints. |

**Decided against:**

| Tool | Why Not |
|------|---------|
| Letta (memory) | **Deferred to Phase 3+.** OpenClaw's built-in context management is sufficient for Phase 1-2. Letta adds complexity (separate server, API, memory management) that isn't needed until we need sophisticated long-term memory across months of interaction. Will re-evaluate when we get there. |
| n8n (workflow orchestration) | **Deferred indefinitely.** The Supervisor handles task decomposition and routing. n8n's Sustainable Use license is problematic for SaaS (Phase 4). If we need visual workflow design later, evaluate Temporal (MIT) instead. |
| Rasa (NLU) | **Not needed.** OpenClaw + Claude Opus handles intent parsing. Rasa OSS is in maintenance mode. |
| Botpress | **Not needed.** OpenClaw covers the same ground with better channel support and MIT license. |
| Appsmith/Refine (admin UI) | **Not needed.** OpenClaw's built-in Control UI handles admin/config. For credential onboarding, we build a minimal page — no need for a full low-code platform. |

---

## 2. High-Level Architecture

Agent Pulsar is a **3-tier event-driven system** with a central message bus. The user-facing layer is powered by OpenClaw; Agent Pulsar owns everything behind it.

```
┌─────────────────────────────────────────────────────────┐
│  Tier 1 — User Interface (LEVERAGED)                    │
│  OpenClaw (MIT)                                         │
│  Channels: Telegram, WhatsApp, Slack, Discord, Signal,  │
│  iMessage, Teams, Web, + 12 more                        │
│  Conversation mgmt, skills system, MCP support          │
│  Custom Agent Pulsar skill: bridges to event bus           │
└──────────────────────┬──────────────────────────────────┘
                       │ Agent Pulsar skill publishes tasks
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Central Nervous System — Event Bus (BUILT)             │
│  Redis Streams (dev) / Kafka (prod)                     │
│  Topics: task.backlog.*, task.status, task.results,     │
│          task.completed, task.dlq, agent.health          │
└──────────────────────┬──────────────────────────────────┘
                       │ supervisor monitors & routes
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Tier 2 — Control Plane (BUILT)                         │
│  Supervisor Agent                                       │
│  Task decomposition, model selection, execution tier    │
│  assignment, health monitoring, retry/DLQ, result       │
│  collection                                             │
└──────────────────────┬──────────────────────────────────┘
                       │ spins up workers on demand
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Tier 3 — Execution Plane (BUILT)                       │
│  Skill Workers (Ephemeral)                              │
│  Stateless, single-task, isolated, zero persistent ctx  │
│  Execution modes: hot (in-process) / warm / cold (Docker)│
│  Tools via MCP (leveraged)                              │
└─────────────────────────────────────────────────────────┘

Cross-cutting: Security Layer — Vault + Token Broker + Audit (BUILT)
Cross-cutting: LLM Gateway — LiteLLM (LEVERAGED)
Cross-cutting: Observability — OpenTelemetry + Langfuse (LEVERAGED)
```

### 2.1 What Agent Pulsar Builds (the novel parts)

1. **Agent Pulsar OpenClaw Skill** — A custom OpenClaw skill that bridges user requests to the Agent Pulsar event bus. This is the glue between the leveraged PA layer and the built orchestration layer.
2. **Event Bus Abstraction** — A unified interface over Redis Streams (dev) and Kafka (prod) with topic management, DLQ, and replay.
3. **Supervisor Agent** — Task decomposition, dependency management, model routing, execution tier selection, health monitoring, retry logic, result collection.
4. **Model Router** — Dynamic model selection based on task complexity, cost optimization, fallback escalation.
5. **Execution Tier Manager** — Hot/warm/cold worker lifecycle management.
6. **Worker Runtime** — Base framework for ephemeral skill workers with credential isolation, heartbeats, and structured result reporting.
7. **Security Layer** — Vault integration, Token Broker, scoped JWT issuance, audit logging.

### 2.2 What Agent Pulsar Leverages

| Tool | Role in Agent Pulsar |
|------|-------------------|
| **OpenClaw** (MIT) | User-facing PA layer + admin UI. Handles all messaging channels (20+), conversation management, skills execution, MCP tool access, and web-based configuration dashboard. |
| **LiteLLM** (MIT) | Unified LLM gateway. All model calls from Supervisor, Model Router, and Workers route through LiteLLM. Single point for cost tracking, retries, and provider switching. |
| **MCP** (open standard) | Tool connectivity. Workers access external APIs (Gmail, Xero, GitHub, etc.) via MCP servers. OpenClaw uses MCP natively for simple tasks. |
| **HashiCorp Vault** (BSL 1.1) | Secrets vault. All user API keys encrypted at rest. Token Broker issues scoped JWTs backed by Vault secrets. |
| **PostgreSQL / Supabase** | Task state persistence. Stores task lifecycle, results, and metadata. |
| **Redis** (BSD-3) | Event bus (dev mode via Redis Streams) + cache + session state. |
| **Docker** (Apache 2.0) | Cold-tier worker isolation. Containers spun up per-task, destroyed after. |

See Section 1.2 for the full locked technology table with rationale.

---

## 3. Tier 1 — PA Agent (OpenClaw Integration)

The user-facing layer is **OpenClaw** — an open-source autonomous AI agent with 20+ messaging channel integrations. Agent Pulsar does not build its own chat interface, channel adapters, or conversation management.

### 3.1 Why OpenClaw

- **MIT license** — fully free for commercial use
- **20+ channels** out of the box: Telegram, WhatsApp, Signal, Slack, Discord, iMessage, Teams, Google Chat, Matrix, IRC, LINE, Web, and more
- **Skills system** — modular architecture where capabilities are defined as SKILL.md files. Agent Pulsar registers as a custom skill.
- **MCP support** — native integration with Model Context Protocol
- **214k+ GitHub stars** — largest open-source AI agent project (as of early 2026), active community, moving to a foundation for governance
- **Handles conversation management** — multi-turn conversations, user context, message formatting are all built-in

### 3.2 Agent Pulsar OpenClaw Skill

The integration point between OpenClaw and Agent Pulsar Core. This is a custom OpenClaw skill that:

| ID | Requirement | Priority |
|----|-------------|----------|
| PA-01 | Register as an OpenClaw skill that intercepts user requests matching Agent Pulsar task categories | Must |
| PA-02 | Publish structured task requests to the Agent Pulsar event bus | Must |
| PA-03 | Listen for completion events from the event bus and relay results back to the user via OpenClaw | Must |
| PA-04 | Provide real-time status updates to the user as tasks progress | Should |
| PA-05 | Handle task confirmation prompts (e.g., "Should I run payroll? This will cost $X") | Must |
| PA-06 | Fall through to OpenClaw's native execution for tasks that don't need Agent Pulsar orchestration | Must |

### 3.3 Routing Decision: OpenClaw Native vs. Agent Pulsar

The Agent Pulsar skill must decide for each user request whether to handle it within OpenClaw or route it to the Agent Pulsar backend. This is a critical decision point.

**Route to Agent Pulsar when ANY of these are true:**
- Task requires access to sensitive credentials (financial APIs, HR systems)
- Task involves multiple steps with dependencies (multi-step workflows)
- Task handles sensitive data (payroll, financial records, PII)
- Task requires a specific model tier (e.g., complex reasoning needed)
- Task type is explicitly registered in the Agent Pulsar skill registry

**Stay in OpenClaw when ALL of these are true:**
- Task is a single-step operation (no decomposition needed)
- Task uses non-sensitive tools (web search, weather, basic calendar reads)
- Task doesn't require Vault-backed credentials
- Task can be handled by OpenClaw's default model

This routing logic is configured via a task registry in the Agent Pulsar skill — a mapping of intent categories to routing decisions. New task types default to OpenClaw unless explicitly registered with Agent Pulsar.

### 3.4 What OpenClaw Handles (we don't build)

- All messaging channel adapters and authentication
- Message normalization across platforms
- Basic conversation management and multi-turn dialogue
- Simple tool execution via MCP (for tasks that don't need Agent Pulsar isolation)
- User onboarding and basic settings

### 3.5 What Agent Pulsar Adds on Top

- Task decomposition into atomic sub-tasks with dependency ordering
- Routing complex/sensitive tasks through the isolated worker pipeline
- Credential isolation (OpenClaw's native MCP calls don't have Vault-backed credential scoping)
- Model selection per task (OpenClaw uses one model for everything)
- Execution tier routing (hot/warm/cold)

### 3.6 Memory (Phase 1-2)

Phase 1-2 uses OpenClaw's built-in context management for conversation state and user preferences. This is sufficient for single-user and small-scale multi-user deployments.

Advanced long-term memory (e.g., self-editing persistent memory across months of interaction) is deferred to Phase 3+. At that point, evaluate Letta (Apache 2.0) or a custom vector store solution based on actual needs.

---

## 4. Central Nervous System — Event Bus

All communication between the PA skill and the Agent Pulsar backend flows through the event bus. No direct calls between OpenClaw and workers.

### 4.1 Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| EB-01 | Provide durable, ordered message delivery | Must |
| EB-02 | Support topic partitioning by skill category (task.backlog.payroll, task.backlog.email, etc.) | Must |
| EB-03 | Support compacted topics for task status tracking | Must |
| EB-04 | Provide dead-letter queue for poison pill messages | Must |
| EB-05 | Support message replay for debugging and recovery | Should |
| EB-06 | Provide a unified abstraction over Redis Streams (dev) and Kafka (prod) | Must |
| EB-07 | Publish task status changes that the OpenClaw skill can subscribe to for user updates | Must |

### 4.2 Topic Schema

| Topic | Purpose | Type |
|-------|---------|------|
| `task.backlog.<skill>` | New tasks partitioned by skill category | Standard |
| `task.status` | Status updates: PENDING, CLAIMED, IN_PROGRESS, COMPLETED, FAILED | Compacted |
| `task.results` | Completed task output payloads | Standard |
| `task.completed` | Enriched completion events for PA consumption | Standard |
| `task.dlq` | Failed tasks after max retries | Standard |
| `agent.health` | Worker heartbeats and health signals | TTL-based |
| `audit.log` | Immutable audit trail of all actions | Append-only |

### 4.3 Message Schemas

#### Task Request (published by OpenClaw skill → consumed by Supervisor)

This is the high-level request before decomposition. The Supervisor will break this into atomic sub-tasks.

```json
{
  "request_id": "uuid",
  "user_id": "user-uuid",
  "conversation_id": "openclaw-conversation-id",
  "intent": "payroll.run",
  "raw_message": "Run payroll for March for all Easyrun employees",
  "params": { "company": "easyrun", "month": "2026-03" },
  "priority": "normal | high | critical",
  "created_at": "ISO-8601"
}
```

#### Atomic Task (created by Supervisor → consumed by Workers)

This is a single decomposed sub-task, ready for worker execution.

```json
{
  "task_id": "uuid",
  "request_id": "uuid (links to parent request)",
  "user_id": "user-uuid",
  "conversation_id": "openclaw-conversation-id",
  "type": "payroll.fetch_employees",
  "params": { "company": "easyrun", "month": "2026-03" },
  "priority": "normal | high | critical",
  "dependencies": ["task_id_1", "task_id_2"],
  "credential_ref": "vault:xero:easyrun | null",
  "execution_tier": "hot | warm | cold",
  "model_assignment": "haiku | sonnet | opus",
  "created_at": "ISO-8601",
  "timeout_ms": 300000,
  "retry_policy": { "max_retries": 3, "backoff": "exponential" }
}
```

#### Task Result (published by Workers → consumed by Supervisor)

```json
{
  "task_id": "uuid",
  "request_id": "uuid",
  "status": "COMPLETED | FAILED",
  "output": { "employees": [...], "count": 4 },
  "error": "null | error description",
  "model_used": "claude-haiku-4-5",
  "execution_tier_used": "hot",
  "duration_ms": 1200,
  "completed_at": "ISO-8601"
}
```

#### Completion Event (published by Supervisor → consumed by OpenClaw skill)

```json
{
  "request_id": "uuid",
  "user_id": "user-uuid",
  "conversation_id": "openclaw-conversation-id",
  "status": "COMPLETED | PARTIAL | FAILED",
  "summary": "March payroll completed for 4 employees. Total: $12,340.",
  "results": [ "...per-task results..." ],
  "total_cost_usd": 0.15,
  "total_duration_ms": 45000,
  "completed_at": "ISO-8601"
}
```

Note: `user_id` is included from the start to support multi-tenant deployment in Phase 4. `conversation_id` links back to the OpenClaw conversation so that results can be routed to the correct user/channel.

---

## 5. Tier 2 — Supervisor Agent (Control Plane)

Orchestrates everything behind the PA layer. **Does NOT execute tasks** — only decomposes, routes, monitors, and manages.

### 5.1 Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| SV-01 | Monitor the event bus for new tasks and route to appropriate workers | Must |
| SV-02 | **Decompose complex task requests into atomic sub-tasks with dependency ordering (DAG)** | Must |
| SV-03 | Maintain a skill registry mapping task types to worker capabilities | Must |
| SV-04 | Track worker health via heartbeats; detect failures and trigger respawns | Must |
| SV-05 | Implement retry logic with exponential backoff for failed tasks | Must |
| SV-06 | Move tasks to DLQ after max retries are exhausted | Must |
| SV-07 | Respect task dependency ordering — do not dispatch a task until its dependencies are COMPLETED | Must |
| SV-08 | Collect results from workers, enrich with summary, publish to task.completed | Must |
| SV-09 | Evaluate task complexity and select the appropriate LLM model for each worker | Must |
| SV-10 | Assign execution tier (hot/warm/cold) based on task requirements | Must |

### 5.2 Components

- **Task Decomposer**: Receives high-level task requests from the OpenClaw skill. Uses Claude Opus (via LiteLLM) to break complex requests into atomic sub-tasks with dependency ordering (DAG). Simple tasks pass through without decomposition.
- **Task Router**: Matches tasks to workers using the skill registry. Considers worker capacity, health, and priority.
- **Model Router**: Evaluates task complexity and selects the cheapest model that can handle it. See section 7.
- **Execution Tier Selector**: Assigns hot/warm/cold execution based on security needs, latency tolerance, and compute requirements. See section 8.
- **Health Monitor**: Tracks worker heartbeats from `agent.health` topic. Detects failures (missed heartbeats, timeout). Triggers worker respawn.
- **Retry & DLQ Handler**: Retries failed tasks with exponential backoff (1s, 2s, 4s, 8s, ...). Moves poison pills to `task.dlq` after max retries.
- **Completion Notifier**: Collects results from `task.results`, enriches with human-readable summary, publishes to `task.completed` for the OpenClaw skill to relay to the user.

### 5.3 Model Selection for Supervisor Itself

The Supervisor's own LLM calls (task decomposition, complexity classification) use Claude Opus via LiteLLM. This is the one component where cost optimization is secondary to reliability — the Supervisor must get decomposition right.

---

## 6. Tier 3 — Skill Workers (Execution Plane)

Stateless, single-task executors. Each worker handles exactly one task, then terminates. Workers access external tools via MCP.

### 6.1 Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| WK-01 | Execute a single atomic task and produce a structured result | Must |
| WK-02 | Request scoped, short-lived credentials from Token Broker — never store credentials | Must |
| WK-03 | Write result to task.results and update task.status on completion or failure | Must |
| WK-04 | Have zero persistent context — complete isolation between task executions | Must |
| WK-05 | Emit heartbeats to agent.health while executing | Must |
| WK-06 | Implement the `SkillWorker` interface for pluggability | Must |
| WK-07 | Respect the assigned execution tier and model | Must |
| WK-08 | Timeout and self-terminate if execution exceeds configured limit | Must |
| WK-09 | Access external APIs exclusively via MCP servers | Must |

### 6.2 Initial Skill Workers

| Worker | Description | MCP Server | Default Tier | Default Model |
|--------|-------------|------------|--------------|---------------|
| Payroll Worker | Run payroll via Xero/QuickBooks | MCP → Xero | Cold | Opus |
| Email Worker | Draft, send, triage email | MCP → Gmail/Outlook | Hot | Haiku/Sonnet |
| Research Worker | Web search, summarize, compile briefs | MCP → Web Search | Warm | Sonnet |
| Calendar Worker | Schedule, reschedule, check availability | MCP → Google Calendar | Hot | Haiku |
| Code Worker | Generate, review, or debug code | MCP → GitHub | Warm | Opus |

### 6.3 Plugin Interface

Custom workers implement the `SkillWorker` interface:

```python
class SkillWorker(ABC):
    """Base interface for all skill workers."""

    @abstractmethod
    def skill_type(self) -> str:
        """The task type this worker handles (e.g., 'payroll.run')."""

    @abstractmethod
    async def execute(self, task: Task, context: ExecutionContext) -> TaskResult:
        """Execute the task and return a result."""

    @abstractmethod
    def capability_requirement(self) -> CapabilityRequirement:
        """Declare the minimum model capability needed for this skill."""

    @abstractmethod
    def default_execution_tier(self) -> ExecutionTier:
        """Declare the default execution tier (hot/warm/cold)."""
```

---

## 7. Dynamic Model Selection (Model Router)

A component of the Supervisor that evaluates each task and selects the most cost-effective model via LiteLLM.

### 7.1 Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| MR-01 | Classify task complexity into tiers: simple, moderate, complex | Must |
| MR-02 | Map complexity tiers to model classes with cost/capability trade-offs | Must |
| MR-03 | Allow skill workers to declare minimum capability requirements | Must |
| MR-04 | Support fallback escalation — if a cheaper model fails, retry with a stronger one | Should |
| MR-05 | Track model performance per task type for continuous optimization | Should |
| MR-06 | Route all model calls through LiteLLM for unified access | Must |

### 7.2 Model Tiers

| Complexity | Model Class | Example Models | Approx Cost/Task |
|------------|-------------|----------------|-------------------|
| **Simple** | Fast/cheap | Haiku, GPT-4o-mini, Llama 3 (local via Ollama) | ~$0.001 |
| **Moderate** | Balanced | Sonnet, GPT-4o | ~$0.01 |
| **Complex** | Max capability | Opus, GPT-4o (high-context) | ~$0.05-0.10 |

### 7.3 Classification Criteria

The Model Router uses a lightweight classifier (Haiku-class model via LiteLLM) to score tasks on:

- **Reasoning depth**: Does the task require multi-step reasoning or just retrieval/formatting?
- **Domain complexity**: Financial calculations vs. sending a canned email
- **Error tolerance**: Payroll must be exact; a calendar invite can tolerate minor issues
- **Worker declaration**: Each worker can declare a minimum capability floor via `capability_requirement()`

### 7.4 Fallback Escalation

If a task fails with a cheaper model and the failure is classified as a capability issue (not an API/tool error), the Supervisor automatically retries with the next model tier up. This is tracked to improve future routing.

---

## 8. Execution Tiers (Latency-Aware Routing)

Not every task needs a Docker container. The Supervisor assigns an execution tier based on the task's requirements.

### 8.1 Tier Definitions

| Tier | Execution Mode | Startup Latency | Isolation | Use Case |
|------|---------------|-----------------|-----------|----------|
| **Hot** | In-process async task / persistent worker session | ~100ms | Process-level | Email send, calendar check, quick lookups — simple tasks with low latency needs |
| **Warm** | Subprocess or pre-warmed container from pool | ~1-2s | Process/container | Document processing, research, drafting — moderate tasks |
| **Cold** | Fresh Docker container, destroyed after use | ~5-10s | Full container | Payroll, financial ops, untrusted code — tasks requiring strong isolation or handling sensitive data |

### 8.2 Tier Assignment Criteria

| Factor | Hot | Warm | Cold |
|--------|-----|------|------|
| Credential access? | Lightweight (long-lived OAuth tokens via Token Broker) | Scoped tokens per task | Scoped tokens, revoked on exit |
| Handles sensitive data? | No | No | Yes |
| Latency-sensitive? | Yes | Moderate | No |
| Compute-intensive? | No | Moderate | Yes |
| Untrusted code execution? | Never | Never | Yes |

**Note on hot tier credentials**: Hot-tier workers (e.g., Email Worker) still need credentials to access APIs like Gmail. However, they use long-lived OAuth refresh tokens managed by the Token Broker, not per-task scoped tokens. The trade-off: less isolation (token persists across tasks) but much lower latency (no per-task Vault round-trip). For non-sensitive operations like sending email, this is acceptable. Sensitive operations always route to cold tier regardless.

### 8.3 Hot Tier: Persistent Worker Sessions

For frequently-used, simple skills (email, calendar), a persistent worker session stays alive and processes multiple tasks sequentially. This avoids cold-start overhead entirely. The session has no cross-task memory — each task still gets a fresh LLM context — but the process and MCP connections stay warm.

---

## 9. Security Layer (Cross-Cutting)

### 9.1 Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| SC-01 | All API keys encrypted at rest (AES-256-GCM) in secrets vault | Must |
| SC-02 | Workers receive only scoped, short-lived tokens (default TTL: 5 min) | Must |
| SC-03 | OpenClaw PA and Supervisor never see raw credentials — only credential references | Must |
| SC-04 | Token Broker revokes tokens on task completion or failure | Must |
| SC-05 | Cold-tier containers run with read-only filesystem, restricted network, resource limits | Must |
| SC-06 | All actions logged to immutable append-only audit trail | Must |
| SC-07 | Inter-service communication uses mTLS | Should |
| SC-08 | User API keys submitted via encrypted channel, written to Vault immediately, never in app memory/logs | Must |
| SC-09 | Users can rotate or revoke their keys at any time | Must |
| SC-10 | OpenClaw's native MCP calls for simple tasks bypass Vault (no sensitive credentials needed) | Should |

### 9.2 Components

- **Secrets Vault** (HashiCorp Vault): All keys encrypted at rest with AES-256-GCM. Self-hosted or Vault on HCP.
- **Token Broker** (built by Agent Pulsar): Issues scoped, time-limited JWT tokens to workers. Interface: `TokenBroker.request(skill, scope, ttl)`. Revokes on task completion.
- **Audit Log**: Append-only event bus topic capturing every credential access, API call, and task lifecycle event. Shipped to cold storage (S3/Azure Blob) for compliance.
- **Config Portal** (built by Agent Pulsar): Minimal web page for secure credential onboarding. See Section 9.5.

### 9.3 Credential Flow

```
Worker starts → requests token from Token Broker
  → Broker validates worker identity + task assignment
  → Broker fetches secret from Vault
  → Broker issues scoped JWT (e.g., xero:payroll:write, TTL 5min)
  → Worker uses JWT to call external API via MCP
  → Task completes → token expires or is revoked
  → Worker container destroyed (cold tier) or context cleared (hot/warm tier)
```

### 9.4 Security Boundary: OpenClaw vs. Agent Pulsar

OpenClaw handles its own simple MCP tool calls (e.g., checking weather, basic web search) without going through Vault. Agent Pulsar's credential isolation only kicks in for tasks routed through the event bus — i.e., tasks that handle sensitive data, require scoped API access, or need execution isolation. This is by design: not every task needs enterprise-grade security, and forcing it would add unnecessary latency.

### 9.5 Credential Onboarding — How Users Provide API Keys

**Problem**: Users need to provide API keys for external services (Xero, Gmail, GitHub, etc.). This must be secure and must NOT happen via chat — pasting credentials in a Telegram/WhatsApp conversation is an anti-pattern (credentials leak through logs, message history, and LLM context windows).

**Solution**: A two-path onboarding flow — OAuth for services that support it, and a minimal secure web form for API keys.

#### Path A: OAuth Flow (preferred, where available)

For services that support OAuth 2.0 (Gmail, Google Calendar, Slack, GitHub, etc.):

```
1. User tells PA: "Connect my Gmail"
2. OpenClaw skill generates a one-time secure link to the Agent Pulsar Config Portal
3. User opens link in browser → sees "Connect Gmail" button
4. User clicks → standard OAuth 2.0 flow with the service provider
5. OAuth callback returns tokens to Config Portal backend
6. Config Portal writes refresh token directly to Vault (key: vault:gmail:<user_id>)
7. Config Portal confirms to user via OpenClaw: "Gmail connected successfully"
```

The user never sees or handles raw tokens. The LLM never sees credentials.

#### Path B: API Key Submission (for services without OAuth)

For services that use static API keys (Xero API key, custom webhooks, etc.):

```
1. User tells PA: "Connect my Xero account"
2. OpenClaw skill generates a one-time, time-limited link (expires in 10 min)
   to the Agent Pulsar Config Portal
3. User opens link in browser → sees a simple form:
   "Enter your Xero API key" + input field + Submit button
4. Form submits via HTTPS directly to the Config Portal backend
5. Backend writes the key directly to Vault (key: vault:xero:<user_id>)
   — key is NEVER stored in application memory, logs, or database
6. Config Portal confirms to user via OpenClaw: "Xero connected successfully"
7. One-time link is invalidated immediately after use
```

#### The Config Portal

A minimal, purpose-built web page (FastAPI + simple HTML/JS) that handles ONLY credential onboarding. This is NOT a full admin dashboard — OpenClaw's Control UI handles general configuration.

| ID | Requirement | Priority |
|----|-------------|----------|
| CP-01 | Serve OAuth 2.0 authorization flows for supported services | Must |
| CP-02 | Serve secure API key submission forms for non-OAuth services | Must |
| CP-03 | Generate one-time, time-limited URLs (default: 10 min expiry) | Must |
| CP-04 | Write credentials directly to Vault — never to disk, logs, or application memory | Must |
| CP-05 | Invalidate one-time URLs immediately after use | Must |
| CP-06 | Show users their connected services and allow key rotation/revocation | Must |
| CP-07 | All pages served over HTTPS only | Must |
| CP-08 | Authenticate users via a token passed from OpenClaw (links the web session to the chat user) | Must |

#### What the User Sees

```
User (via Telegram): "Connect my Xero account"

PA: "To securely connect Xero, open this link:
     https://config.agentpulsar.app/connect/abc123def
     (expires in 10 minutes)

     I'll never ask you to paste API keys in this chat."

[User opens link → enters API key → submits]

PA: "Xero connected! I can now run payroll for you.
     You can manage your connections anytime at:
     https://config.agentpulsar.app/connections"
```

#### Connected Services Dashboard

The Config Portal also serves a `/connections` page where users can:
- See all connected services and their status
- Rotate API keys (submit a new key, old one is revoked)
- Revoke/disconnect a service
- See when each credential was last used (from audit log)

This page is accessible via a persistent authenticated link (not one-time), generated from OpenClaw when the user asks "manage my connections" or similar.

---

## 10. Data Flow Examples

### 10.1 Complex Task: "Run payroll for March for all Easyrun employees"

**Step 1: OpenClaw receives message**
User sends message via Telegram. OpenClaw receives it through its Telegram channel adapter. The Agent Pulsar skill recognizes this as a task requiring orchestration (payroll = sensitive, multi-step).

**Step 2: Agent Pulsar skill publishes to event bus**
The skill publishes a high-level task request to `task.backlog.payroll` with `conversation_id` linking back to the OpenClaw conversation. OpenClaw replies to user: "On it — running payroll for March. I'll update you when done."

**Step 3: Supervisor decomposes and routes**
Supervisor picks up the task. Task Decomposer (Opus via LiteLLM) creates 4 atomic sub-tasks:
1. `fetch_employee_list` (no dependencies)
2. `calculate_payroll` (depends on 1)
3. `submit_payroll` (depends on 2)
4. `send_payslips` (depends on 3)

Model Router classifies as complex → assigns Opus. Execution Tier Selector assigns cold (sensitive financial data). Dispatches task 1 first.

**Step 4: Worker executes**
Payroll Worker container spins up. Requests scoped `xero:payroll:write` token (TTL 5min) from Token Broker. Executes task via MCP → Xero. Writes result to `task.results`. Updates `task.status` → COMPLETED. Container terminates. Token auto-revoked.

Supervisor dispatches next task in chain. Repeat until all 4 complete.

**Step 5: Result returned to user**
Supervisor collects all results, enriches with summary, publishes to `task.completed`. Agent Pulsar OpenClaw skill picks up completion event, sends via OpenClaw → Telegram: "Done — March payroll completed for 4 employees. Total: $12,340. Payslips sent."

### 10.2 Simple Task: "What's on my calendar today?"

**Step 1: OpenClaw receives message**
User sends via Telegram. OpenClaw's Agent Pulsar skill evaluates: this is a simple, non-sensitive read operation.

**Step 2: OpenClaw handles directly**
This task does NOT go through the Agent Pulsar event bus. OpenClaw uses its native MCP integration to call Google Calendar directly and responds to the user. No Supervisor, no worker isolation, no Vault — because none are needed.

**This is the key architectural decision**: not every task needs orchestration. Simple, non-sensitive tasks stay in OpenClaw. Complex, sensitive, or multi-step tasks route through Agent Pulsar.

### 10.3 Credential Onboarding: "Connect my Xero account"

**Step 1: User requests connection**
User sends "connect my Xero account" via Telegram.

**Step 2: Agent Pulsar skill generates secure link**
The skill calls the Config Portal API to generate a one-time URL (10-min expiry) tied to this user. Responds via OpenClaw: "Open this link to securely connect Xero: https://config.agentpulsar.app/connect/abc123 (expires in 10 min). I'll never ask you to paste API keys in chat."

**Step 3: User submits credentials via browser**
User opens the link → sees a simple form → enters their Xero API key → clicks Submit. Form sends the key over HTTPS directly to the Config Portal backend.

**Step 4: Config Portal stores in Vault**
Config Portal writes the key to Vault (`vault:xero:<user_id>`). Key is never stored in application memory, logs, database, or OpenClaw. One-time link is immediately invalidated.

**Step 5: Confirmation**
Config Portal notifies OpenClaw via the event bus. PA responds: "Xero connected! I can now run payroll for you."

---

## 11. Tech Stack (Locked)

All choices are final. See Section 1.2 for rationale behind each decision.

### Leveraged (we deploy and configure, not build)

| Component | Technology | License | Phase |
|-----------|-----------|---------|-------|
| PA / Chat Interface | OpenClaw | MIT | 1 |
| Admin / Config UI | OpenClaw Control UI | MIT | 1 |
| LLM Gateway | LiteLLM | MIT | 1 |
| Tool Connectivity | MCP | Open standard | 1 |
| Secrets Vault | HashiCorp Vault | BSL 1.1 | 2 |
| Task State DB | PostgreSQL (Supabase) | PostgreSQL License | 1 |
| Cache + Event Bus (dev) | Redis | BSD-3 | 1 |
| Event Bus (prod) | Apache Kafka (Confluent Cloud) | Apache 2.0 | 3 |
| Schema Registry (prod) | Confluent Schema Registry | Confluent Community License | 3 |
| Container Runtime | Docker | Apache 2.0 | 2 |
| Container Orchestrator (prod) | Kubernetes | Apache 2.0 | 3 |
| Tracing | OpenTelemetry + Langfuse | Apache 2.0 / MIT | 4 |
| Metrics + Dashboards | Prometheus + Grafana | Apache 2.0 | 4 |
| Alerting | PagerDuty | Commercial (free tier) | 4 |

### Built (Agent Pulsar Core — what we write)

| Component | Technology | Phase |
|-----------|-----------|-------|
| Agent Pulsar OpenClaw Skill | Python (OpenClaw skills SDK) | 1 |
| Event Bus Abstraction | Python (Redis Streams adapter, Kafka adapter) | 1 |
| Supervisor Agent | Python + FastAPI + asyncio | 1 |
| Model Router | Python + LiteLLM | 1 |
| Execution Tier Manager | Python | 1 |
| Worker Runtime (base framework) | Python + asyncio | 1 |
| Token Broker | Python + FastAPI + PyJWT | 2 |
| Config Portal (credential onboarding) | Python + FastAPI + minimal HTML/JS | 2 |
| Audit Logger | Python + event bus adapter | 2 |

### LLM Models (via LiteLLM)

| Role | Model | When Used |
|------|-------|-----------|
| Supervisor (decomposition) | Claude Opus 4.6 | Always — reliability over cost |
| Model Router (classification) | Claude Haiku 4.5 | Always — cheap, fast classification |
| Workers — simple tier | Claude Haiku 4.5 | Email send, calendar check, quick lookups |
| Workers — moderate tier | Claude Sonnet 4.6 | Research, drafting, document processing |
| Workers — complex tier | Claude Opus 4.6 | Payroll, financial ops, code generation |
| Local fallback | Ollama + Llama 3.3 | Offline mode, zero-cost dev testing |

**Note on model choice**: We default to Claude models across the board for consistency and because the Anthropic API supports structured output, tool use, and long context natively. LiteLLM allows swapping to GPT or open-source models per-worker if needed, but the default configuration uses Claude.

---

## 12. Competitive Differentiation

### 12.1 Feature Comparison

| Feature | CrewAI | LangGraph | AutoGen | OpenClaw (standalone) | **Agent Pulsar** |
|---------|--------|-----------|---------|----------------------|----------------|
| Event-driven backlog | No | Partial | No | No | **Redis Streams / Kafka** |
| Ephemeral workers | No | No | No | No | **Per-task isolation** |
| 3-tier separation | Partial | No | Partial | No | **PA / Supervisor / Workers** |
| Credential isolation | No | No | No | No | **Vault + scoped tokens** |
| Dynamic model selection | No | No | No | No | **Model Router** |
| Execution tiers | No | No | No | No | **Hot / Warm / Cold** |
| Worker context isolation | No | Partial | No | No | **Complete isolation** |
| DLQ / retry logic | No | Partial | No | No | **Native DLQ + backoff** |
| Chat-first (20+ channels) | No | No | No | Yes | **Yes (via OpenClaw)** |
| MCP native | Partial | Partial | Partial | Yes | **Yes** |

### 12.2 Positioning

Agent Pulsar is **not** a replacement for OpenClaw — it is the **orchestration backend** that makes OpenClaw enterprise-grade. OpenClaw alone is a great single-agent assistant. Agent Pulsar + OpenClaw is a **distributed, fault-tolerant, cost-optimized multi-agent system** with a chat-first interface.

Think of it as: **OpenClaw is the frontend, Agent Pulsar is the backend**. Like how Next.js is the frontend and Kubernetes is the orchestration — they solve different problems and work together.

---

## 13. Development Phases

### Phase 1 — Core Loop (MVP)

**Goal**: Prove the decomposition → event bus → worker → result loop works end-to-end.

- Deploy OpenClaw with Telegram channel
- Build Agent Pulsar OpenClaw skill (bridge between OpenClaw and event bus)
- Redis Streams as event bus
- Supervisor with task decomposition (Opus via LiteLLM) and basic routing
- Basic Model Router (simple/moderate/complex classification via Haiku)
- 2 skill workers: Email Worker (hot tier) + Research Worker (warm tier)
- PostgreSQL for task state
- In-process (hot) and subprocess (warm) execution only — no Docker yet
- Decision logic in OpenClaw skill: simple tasks stay in OpenClaw, complex tasks route to Agent Pulsar

**Deliverable**: User sends "research X and email me a summary" via Telegram → OpenClaw receives → Agent Pulsar decomposes into research + email tasks → workers execute → result returned to user via Telegram.

### Phase 2 — Security & Cold Tier

**Goal**: Add credential isolation and container-based execution for sensitive tasks.

- HashiCorp Vault integration (self-hosted or HCP)
- Token Broker (FastAPI service) with scoped JWT issuance
- Config Portal (FastAPI + minimal HTML/JS) for secure credential onboarding:
  - OAuth flows for Gmail, Google Calendar, Slack, GitHub
  - API key submission forms for Xero and other non-OAuth services
  - Connected services dashboard (`/connections` page)
- Cold tier: Docker container execution for sensitive tasks
- Audit logging to event bus topic
- Add Payroll Worker + Calendar Worker

**Deliverable**: User sends "connect my Xero" → opens secure link → submits key → key stored in Vault. User sends "run payroll" → task routes through cold tier with Vault-backed credentials → fully isolated execution.

### Phase 3 — Scale & Reliability

**Goal**: Production-grade reliability.

- Migrate event bus to Kafka (Confluent Cloud)
- Confluent Schema Registry for message validation
- Full DLQ and retry logic with exponential backoff
- Health monitoring and automatic worker respawn
- Model Router with fallback escalation and performance tracking
- Kubernetes deployment
- Evaluate advanced memory needs — if needed, integrate Letta (Apache 2.0) or custom vector store

**Deliverable**: System handles failures gracefully (retries, DLQ), optimizes model costs automatically, runs on Kubernetes.

### Phase 4 — Platform & Observability

**Goal**: Multi-tenant SaaS readiness and operational visibility.

- Full observability stack (OpenTelemetry, Langfuse, Prometheus, Grafana)
- Multi-tenant support (user isolation, per-tenant Vault namespaces)
- Plugin SDK for third-party skill workers
- Admin dashboard for monitoring, cost tracking, audit review
- Documentation and onboarding for external developers

**Deliverable**: Agent Pulsar can be deployed as a multi-tenant SaaS platform where each user gets their own isolated agent system behind a single chat interface.

---

## Appendix A: License Compliance

All leveraged tools have been verified for commercial use:

| Tool | License | Commercial Use | Restrictions |
|------|---------|---------------|-------------|
| OpenClaw | MIT | Unrestricted | Attribution only |
| LiteLLM | MIT | Unrestricted | Attribution only |
| MCP | Open standard | Unrestricted | None |
| Redis | BSD-3 | Unrestricted | Attribution + disclaimer |
| PostgreSQL | PostgreSQL License | Unrestricted | Attribution only |
| Docker | Apache 2.0 | Unrestricted | Attribution + notice |
| Kubernetes | Apache 2.0 | Unrestricted | Attribution + notice |
| Apache Kafka | Apache 2.0 | Unrestricted | Attribution + notice |
| HashiCorp Vault | BSL 1.1 | Free for non-competing use | Cannot offer a managed Vault-as-a-service product. Using Vault as credential store inside Agent Pulsar (even as SaaS) is allowed. |
| OpenTelemetry | Apache 2.0 | Unrestricted | Attribution + notice |
| Langfuse | MIT | Unrestricted | Attribution only |
| Prometheus | Apache 2.0 | Unrestricted | Attribution + notice |
| Grafana | AGPL-3.0 | Free for internal dashboards | If embedding Grafana in a customer-facing SaaS product, a commercial license may be needed. Self-hosted internal dashboards are fine. |

**Note on HashiCorp Vault BSL 1.1**: The restriction is narrow — you cannot offer "HashiCorp Vault as a managed service." Using Vault as an internal component of Agent Pulsar (even in a SaaS deployment) is explicitly allowed. This has been confirmed by HashiCorp's FAQ.

**Note on Grafana AGPL-3.0**: For Phase 4 SaaS, if Grafana dashboards are exposed to end users, evaluate whether a Grafana Cloud commercial license is needed. Internal-only dashboards (ops team) have no restriction.
