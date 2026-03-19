# Agent Pulsar — Project Tracker

> Last updated: 2026-03-19

---

## Phase Overview

| Phase | Focus | Status |
|-------|-------|--------|
| **Phase 1** | Core loop: event bus, supervisor, 2 workers | **COMPLETE** |
| **Phase 2** | Security & isolation: Vault, Token Broker, cold tier, new workers | **COMPLETE** |
| **Phase 3** | Scale: Kafka, Kubernetes, advanced retry, memory | Not started |
| **Phase 4** | Platform: multi-tenant SaaS, observability, plugin SDK | Not started |

---

## Phase 1 — Core Loop (COMPLETE)

All items implemented, tested (34 unit tests), committed, and pushed to GitHub.

| Component | Status | Tests | Notes |
|-----------|--------|-------|-------|
| Event bus abstraction (`event_bus/base.py`) | Done | 7 unit | ABC interface, Redis Streams impl |
| Redis Streams impl (`event_bus/redis_streams.py`) | Done | 7 unit | Publish, subscribe, consumer groups, DLQ, ack |
| Pydantic schemas (`schemas/`) | Done | 17 unit | TaskRequest, AtomicTask, TaskResult, StatusUpdate, CompletionEvent |
| Supervisor HTTP API (`supervisor/api.py`) | Done | — | POST /tasks, GET /tasks/{id}, GET /health |
| Task Decomposer (`supervisor/decomposer.py`) | Done | — | Opus via LiteLLM, DAG-based decomposition |
| Model Router (`supervisor/model_router.py`) | Done | 9 unit | Haiku classifies complexity → cheapest model |
| Task Scheduler (`supervisor/scheduler.py`) | Done | — | DAG-aware dispatch, dependency tracking |
| Skill Registry (`supervisor/registry.py`) | Done | — | Task type → topic routing |
| Completion Notifier (`supervisor/collector.py`) | Done | — | Result collection + summary generation |
| Email Worker (`workers/email_worker.py`) | Done | — | Hot tier, SIMPLE, drafts emails via LLM |
| Research Worker (`workers/research_worker.py`) | Done | — | Warm tier, MODERATE, research summaries |
| Worker Runner (`workers/runner.py`) | Done | — | Subscribe → deserialize → execute → publish |
| PostgreSQL persistence (`persistence/`) | Done | — | ORM models, repository, Alembic migrations |
| Config (`config.py`) | Done | — | Pydantic Settings, AP_ prefix |
| OpenClaw Skill (`skills/agent-pulsar/`) | Done | — | Bridge to event bus |
| Docker Compose (Redis + PostgreSQL) | Done | — | Dev infrastructure |
| Initial Alembic migration | Done | — | task_requests + atomic_tasks tables |

---

## Phase 2 — Security & Isolation (COMPLETE)

All items implemented, tested (77 total unit tests), committed, and pushed to GitHub.

### Security Layer

| Component | Status | Tests | Files |
|-----------|--------|-------|-------|
| Vault client abstraction | Done | 9 unit | `security/vault_client.py` |
| MemoryVaultClient (dev/test) | Done | 9 unit | `security/vault_client.py` |
| HvacVaultClient (real Vault) | Done | — | `security/vault_client.py` (needs integration test with Vault dev server) |
| Token Broker core | Done | 6 unit | `security/token_broker.py` |
| Token Broker HTTP API | Done | 5 unit | `security/broker_api.py` |
| Token Broker schemas | Done | — | `security/schemas.py` |
| Credential Provider protocol | Done | 3 unit | `security/credential_provider.py` |
| TokenBrokerCredentialProvider | Done | — | `security/credential_provider.py` (needs integration test) |
| NoopCredentialProvider | Done | 3 unit | `security/credential_provider.py` |

### Cold Tier Execution

| Component | Status | Tests | Files |
|-----------|--------|-------|-------|
| DockerTaskRunner | Done | 4 unit | `workers/docker_runner.py` |
| Cold tier entrypoint | Done | — | `workers/cold_entrypoint.py` |
| Payroll Dockerfile | Done | — | `docker/payroll/Dockerfile` |
| WorkerRunner cold delegation | Done | — | `workers/runner.py` (if tier==COLD, delegate to DockerTaskRunner) |

### Config Portal

| Component | Status | Tests | Files |
|-----------|--------|-------|-------|
| Link manager (Redis-backed one-time URLs) | Done | 3 unit | `config_portal/link_manager.py` |
| Portal API routes | Done | 5 unit | `config_portal/routes.py` |
| Portal schemas | Done | — | `config_portal/schemas.py` |
| Portal FastAPI app | Done | — | `config_portal/app.py` |
| HTML templates (connect, success, error, connections) | Done | — | `config_portal/templates/` |

### New Workers

| Component | Status | Tests | Files |
|-----------|--------|-------|-------|
| Payroll Worker (cold tier, COMPLEX) | Done | 4 unit | `workers/payroll_worker.py` |
| Calendar Worker (hot tier, SIMPLE) | Done | 4 unit | `workers/calendar_worker.py` |
| Registry entries (payroll + calendar) | Done | — | `supervisor/registry.py` |
| Decomposer prompt (payroll + calendar task types) | Done | — | `supervisor/decomposer.py` |

### Phase 2 Config Additions

| Setting | Default | Purpose |
|---------|---------|---------|
| `AP_VAULT_URL` | None (uses MemoryVaultClient) | HashiCorp Vault endpoint |
| `AP_VAULT_TOKEN` | None | Vault auth token |
| `AP_VAULT_MOUNT_POINT` | `"secret"` | Vault KV mount |
| `AP_TOKEN_BROKER_SECRET` | `"dev-secret-change-me"` | JWT signing key |
| `AP_TOKEN_BROKER_HOST/PORT/URL` | `0.0.0.0:8101` | Token Broker service |
| `AP_DEFAULT_TOKEN_TTL_SECONDS` | `300` | Default JWT TTL |
| `AP_DOCKER_NETWORK` | `"agent-pulsar-net"` | Docker network for cold tier |
| `AP_COLD_TIER_MEM_LIMIT` | `"512m"` | Container memory limit |
| `AP_COLD_TIER_CPU_QUOTA` | `50000` | Container CPU quota |
| `AP_CONFIG_PORTAL_HOST/PORT/BASE_URL` | `0.0.0.0:8102` | Config Portal service |
| `AP_ONBOARDING_LINK_TTL_SECONDS` | `600` | One-time link expiry |

### Phase 2 Dependencies Added

| Package | Version | Purpose |
|---------|---------|---------|
| `hvac` | >=2.3 | HashiCorp Vault client |
| `PyJWT` | >=2.9 | JWT token issuance |
| `jinja2` | >=3.1 | Config Portal templates |
| `python-multipart` | >=0.0.9 | Form parsing for credential submission |

---

## Phase 3 — Scale (NOT STARTED)

| Component | Status | Notes |
|-----------|--------|-------|
| Kafka migration (replace Redis Streams) | Not started | EventBus abstraction makes this transparent |
| Schema Registry (Confluent) | Not started | JSON schema validation for event bus messages |
| Kubernetes deployment | Not started | Helm charts, pod autoscaling |
| Full DLQ replay + advanced retry | Not started | Admin API, replay capability, alerting |
| Advanced memory (Letta or vector store) | Not started | Long-term memory across sessions |
| Code Worker | Not started | Code generation/review tasks |

---

## Phase 4 — Platform (NOT STARTED)

| Component | Status | Notes |
|-----------|--------|-------|
| Multi-tenant support | Not started | User isolation, billing, quotas |
| Observability (OpenTelemetry + Langfuse) | Not started | Distributed tracing, LLM cost tracking |
| Prometheus + Grafana | Not started | Metrics and dashboarding |
| Plugin SDK for third-party workers | Not started | Public API for community workers |

---

## Validation Checklist

| Check | Phase 1 | Phase 2 |
|-------|---------|---------|
| Unit tests pass | 34/34 | 77/77 |
| Ruff lint clean | Yes | Yes |
| MyPy strict clean | Yes | Yes |
| Alembic migrations run | Yes | Yes |
| Docker services healthy | Yes | Yes |
| GitHub repo pushed | Yes | Yes |
| Integration tests | Not yet written | Not yet written |
| E2E tests | Not yet written | Not yet written |

---

## Known Gaps / Tech Debt

1. **Integration tests** — directories exist but no tests written yet. Need real Redis + PostgreSQL tests.
2. **E2E tests** — need full stack (Supervisor + workers + event bus) running to test task flow end-to-end.
3. **HvacVaultClient integration test** — needs a Vault dev server in CI.
4. **TokenBrokerCredentialProvider integration test** — needs running Token Broker service.
5. **Cold tier integration test** — needs Docker to run actual container.
6. **MCP tool integration** — workers currently use LLM simulation, not real external API calls via MCP.
7. **OAuth flows in Config Portal** — backend routes exist but OAuth provider integration is stubbed.
8. **Supervisor API auth** — Phase 1/2 has no auth; needs Bearer token via Vault in production.
