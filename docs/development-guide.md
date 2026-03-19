# Agent Pulsar -- Development Guide

> Version: 0.1.0 | Last updated: 2026-03-19

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12+ | Runtime. The project uses modern Python features (type unions with `\|`, `match` statements). |
| [uv](https://docs.astral.sh/uv/) | latest | Python package manager. Handles virtualenv creation, dependency resolution, and lockfile. |
| Docker + Docker Compose | latest | Runs Redis and PostgreSQL for local development. |
| Git | 2.x+ | Source control. |

Optional but recommended:

| Tool | Purpose |
|------|---------|
| [Ruff](https://docs.astral.sh/ruff/) | Linting and formatting (installed as dev dependency, but IDE integration is helpful) |
| [pgcli](https://www.pgcli.com/) | Interactive PostgreSQL client with auto-completion |
| [redis-cli](https://redis.io/docs/getting-started/) | Inspect Redis streams directly |

---

## Initial Setup

### 1. Clone the repository

```bash
git clone <repository-url> agent-pulsar
cd agent-pulsar
```

### 2. Install dependencies

```bash
uv sync --all-extras
```

This creates a virtual environment in `.venv/`, installs all runtime and dev dependencies, and generates `uv.lock`.

### 3. Start infrastructure services

```bash
docker compose up -d
```

This starts:
- **Redis** on `localhost:6379` -- event bus (Redis Streams) and cache
- **PostgreSQL** on `localhost:5432` -- task state database (db: `agent_pulsar`, user: `agent_pulsar`, password: `agent_pulsar`)

Verify services are healthy:

```bash
docker compose ps
```

Both should show `healthy` status.

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

```bash
# Required -- your Anthropic API key for LLM calls via LiteLLM
AP_ANTHROPIC_API_KEY=sk-ant-...
```

All other values have sensible defaults for local development. See `.env.example` for the full list.

**Environment variable reference**:

| Variable | Default | Description |
|----------|---------|-------------|
| `AP_ANTHROPIC_API_KEY` | (required) | Anthropic API key for Claude models |
| `AP_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `AP_DATABASE_URL` | `postgresql+asyncpg://agent_pulsar:agent_pulsar@localhost:5432/agent_pulsar` | PostgreSQL connection URL |
| `AP_SUPERVISOR_HOST` | `0.0.0.0` | Supervisor API bind address |
| `AP_SUPERVISOR_PORT` | `8100` | Supervisor API port |
| `AP_DECOMPOSITION_MODEL` | `claude-opus-4-0-20250514` | Model for task decomposition (Supervisor) |
| `AP_CLASSIFICATION_MODEL` | `claude-haiku-4-5-20250414` | Model for complexity classification (Model Router) |
| `AP_OPENCLAW_WEBHOOK_URL` | `http://localhost:18789/hooks/agent` | OpenClaw callback URL for result delivery |
| `AP_CONSUMER_GROUP` | `agent-pulsar-supervisor` | Default consumer group for the Supervisor |
| `AP_EVENT_BUS_POLL_MS` | `1000` | Event bus polling interval in milliseconds |
| `AP_MAX_RETRIES` | `3` | Maximum retry attempts for failed tasks |

### 5. Run database migrations

```bash
uv run alembic upgrade head
```

This creates the `task_requests` and `atomic_tasks` tables in PostgreSQL.

To create a new migration after modifying models:

```bash
uv run alembic revision --autogenerate -m "description of change"
```

---

## Running the Application

### Start the Supervisor

```bash
uv run uvicorn agent_pulsar.supervisor.app:app --host 0.0.0.0 --port 8100 --reload
```

The Supervisor:
- Exposes the HTTP API at `http://localhost:8100`
- Consumes from `task.submitted` and `task.results` on the event bus
- Decomposes tasks and dispatches to `task.backlog.<skill>` topics

Verify it is running:

```bash
curl http://localhost:8100/health
```

### Start workers

Workers are started via the worker runner script. Each worker type runs as a separate process:

```bash
# Start the Email Worker (hot tier, in-process)
uv run python scripts/run_worker.py email

# Start the Research Worker (warm tier, subprocess)
uv run python scripts/run_worker.py research
```

Workers consume from their respective `task.backlog.<skill>` topic and publish results to `task.results`.

### Submit a test task

```bash
curl -X POST http://localhost:8100/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user",
    "conversation_id": "test-conv-1",
    "intent": "research.summarize",
    "raw_message": "Research the latest trends in distributed AI systems and email me a summary",
    "params": {},
    "priority": "normal"
  }'
```

Check task status:

```bash
curl http://localhost:8100/tasks/<request_id>
```

---

## OpenClaw Integration Setup

Agent Pulsar uses OpenClaw as the user-facing chat layer. For local development:

### 1. Install and run OpenClaw

Follow the OpenClaw installation guide to run it locally. The default configuration exposes:
- Chat API on port `18789`
- Control UI (admin dashboard) at `http://localhost:18789`

### 2. Register the Agent Pulsar skill

Copy the Agent Pulsar skill definition into your OpenClaw skills directory:

```bash
cp -r skills/agent-pulsar/ <openclaw-root>/skills/agent-pulsar/
```

The skill directory contains a `SKILL.md` file that OpenClaw uses to register the skill and determine when to invoke it.

### 3. Configure the webhook

Ensure the OpenClaw webhook URL is set in your `.env`:

```bash
AP_OPENCLAW_WEBHOOK_URL=http://localhost:18789/hooks/agent
```

The Agent Pulsar OpenClaw Skill listens for `task.completed` events on the event bus and POSTs results to this URL for delivery to the user.

### 4. Connect a messaging channel

Use the OpenClaw Control UI (`http://localhost:18789`) to connect a messaging channel (Telegram is recommended for development). Follow OpenClaw's channel setup guide for your preferred platform.

---

## Running Tests

### Unit tests

```bash
uv run pytest tests/unit/ -v
```

Unit tests do not require Docker services. They use `fakeredis` for event bus tests and SQLite in-memory for database tests.

### Integration tests

```bash
uv run pytest tests/integration/ -v -m integration
```

Integration tests require running Redis and PostgreSQL (via `docker compose up -d`). They test actual event bus publish/subscribe flows and database operations.

### End-to-end tests

```bash
uv run pytest tests/e2e/ -v -m e2e
```

E2E tests require the full stack: Redis, PostgreSQL, Supervisor, and at least one worker. They submit tasks via the HTTP API and verify results flow through the entire pipeline.

### All tests

```bash
uv run pytest
```

### Test with coverage

```bash
uv run pytest --cov=agent_pulsar --cov-report=term-missing
```

---

## Project Structure

```
agent-pulsar/
|-- alembic/                  # Database migration scripts
|   |-- env.py                # Alembic configuration
|   +-- versions/             # Migration files
|-- docs/                     # Documentation
|   |-- requirements.md       # Full requirements & architecture spec
|   |-- design.md             # System design document
|   |-- api-spec.md           # Supervisor HTTP API specification
|   |-- event-schema.md       # Event bus message schemas
|   +-- development-guide.md  # This file
|-- scripts/                  # Utility scripts
|   +-- run_worker.py         # Worker launcher script
|-- skills/                   # OpenClaw skill definitions
|   +-- agent-pulsar/         # Agent Pulsar OpenClaw Skill
|-- src/
|   +-- agent_pulsar/         # Main Python package
|       |-- __init__.py
|       |-- config.py         # Settings (Pydantic BaseSettings, AP_ prefix)
|       |-- schemas/          # Pydantic models for events and enums
|       |   |-- __init__.py
|       |   |-- enums.py      # TaskStatus, Priority, ExecutionTier, ComplexityTier
|       |   +-- events.py     # TaskRequest, AtomicTask, TaskResult, etc.
|       |-- event_bus/        # Event bus abstraction and implementations
|       |   |-- __init__.py
|       |   |-- base.py       # Abstract EventBus interface
|       |   +-- redis_streams.py  # Redis Streams implementation
|       |-- persistence/      # Database layer
|       |   |-- __init__.py
|       |   |-- database.py   # SQLAlchemy engine and session factory
|       |   |-- models.py     # ORM models (TaskRequestRecord, AtomicTaskRecord)
|       |   +-- repository.py # TaskRepository (CRUD operations)
|       |-- supervisor/       # Supervisor agent (Tier 2)
|       |   +-- __init__.py
|       +-- workers/          # Skill workers (Tier 3)
|           +-- __init__.py
|-- tests/
|   |-- __init__.py
|   |-- unit/                 # Unit tests (no external services)
|   |   |-- __init__.py
|   |   |-- test_schemas.py
|   |   +-- test_event_bus.py
|   |-- integration/          # Integration tests (requires Docker services)
|   |   +-- __init__.py
|   +-- e2e/                  # End-to-end tests (requires full stack)
|       +-- __init__.py
|-- .env.example              # Environment variable template
|-- .gitignore
|-- .python-version           # Python version pin (3.12)
|-- alembic.ini               # Alembic configuration
|-- docker-compose.yml        # Redis + PostgreSQL for local dev
+-- pyproject.toml            # Project metadata, dependencies, tool config
```

---

## Code Style and Linting

The project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, configured in `pyproject.toml`:

- **Target**: Python 3.12
- **Line length**: 100 characters
- **Lint rules**: E, F, I, N, W, UP, B, A, SIM, TCH (pyflakes, isort, naming, bugbear, simplify, type-checking)

### Run the linter

```bash
uv run ruff check src/ tests/
```

### Auto-fix lint issues

```bash
uv run ruff check src/ tests/ --fix
```

### Format code

```bash
uv run ruff format src/ tests/
```

### Type checking

```bash
uv run mypy src/
```

MyPy is configured in strict mode with the Pydantic plugin enabled.

---

## Contributing Guidelines

### Before submitting a change

1. **Run linting**: `uv run ruff check src/ tests/`
2. **Run type checks**: `uv run mypy src/`
3. **Run tests**: `uv run pytest` (all tests must pass)
4. **Add tests**: Every new feature or bug fix should include tests. Unit tests at minimum; integration tests for event bus or database changes.

### Code conventions

- All Pydantic models use `model_config = ConfigDict(frozen=True)` for immutability.
- Event bus messages are defined in `src/agent_pulsar/schemas/events.py`. Do not create message types elsewhere.
- All configuration uses the `AP_` environment variable prefix (via `pydantic-settings`).
- Async everywhere: all I/O operations (Redis, PostgreSQL, HTTP) use async/await. Do not use synchronous I/O in the main application code.
- Use `logging` (not `print`) for all output. Logger name should match the module: `logger = logging.getLogger(__name__)`.
- Imports are organized by Ruff's isort rules: stdlib, third-party, first-party.

### Testing requirements

| Change Type | Required Tests |
|-------------|---------------|
| New Pydantic schema | Unit test: serialization round-trip, field defaults, validation |
| New event bus behavior | Unit test with fakeredis + integration test with real Redis |
| New API endpoint | Unit test for request validation + integration test for full request cycle |
| New worker | Unit test for execute() logic + e2e test for task submission through completion |
| Database model change | New Alembic migration + integration test |

### Branch and PR workflow

1. Create a feature branch from `main`: `git checkout -b feature/your-feature`
2. Make changes, commit with clear messages.
3. Ensure all checks pass locally.
4. Open a pull request against `main`.

---

## Useful Commands Reference

```bash
# --- Setup ---
uv sync --all-extras              # Install all dependencies
docker compose up -d              # Start Redis + PostgreSQL
docker compose down               # Stop services
docker compose down -v            # Stop services and delete data volumes
cp .env.example .env              # Create local config

# --- Database ---
uv run alembic upgrade head       # Apply all migrations
uv run alembic downgrade -1       # Revert last migration
uv run alembic revision --autogenerate -m "description"  # Generate migration

# --- Run ---
uv run uvicorn agent_pulsar.supervisor.app:app --port 8100 --reload   # Supervisor
uv run python scripts/run_worker.py email                              # Email Worker
uv run python scripts/run_worker.py research                           # Research Worker

# --- Test ---
uv run pytest                                # All tests
uv run pytest tests/unit/ -v                 # Unit tests only
uv run pytest tests/integration/ -v          # Integration tests only
uv run pytest --cov=agent_pulsar             # Tests with coverage

# --- Lint ---
uv run ruff check src/ tests/               # Lint
uv run ruff check src/ tests/ --fix         # Auto-fix
uv run ruff format src/ tests/              # Format
uv run mypy src/                            # Type check

# --- Debug ---
redis-cli XLEN task.submitted               # Check event bus topic length
redis-cli XRANGE task.submitted - +         # Read all messages in a topic
redis-cli XINFO GROUPS task.submitted       # Check consumer groups
```

---

## Troubleshooting

### Docker services not starting

```bash
docker compose logs redis
docker compose logs postgres
```

Common issues:
- Port 6379 or 5432 already in use: stop other Redis/PostgreSQL instances or change ports in `docker-compose.yml`.
- Insufficient disk space for PostgreSQL volume.

### Alembic migration fails

If you see "Target database is not up to date":

```bash
uv run alembic stamp head    # Mark current state as up-to-date
uv run alembic upgrade head  # Re-run migrations
```

If you need to start fresh:

```bash
docker compose down -v       # Delete database volume
docker compose up -d         # Recreate fresh database
uv run alembic upgrade head  # Apply all migrations
```

### Event bus messages not being consumed

1. Check that the consumer group exists:
   ```bash
   redis-cli XINFO GROUPS task.submitted
   ```
2. Check for pending (unacknowledged) messages:
   ```bash
   redis-cli XPENDING task.submitted agent-pulsar-supervisor
   ```
3. Check the DLQ for failed messages:
   ```bash
   redis-cli XRANGE task.dlq - +
   ```

### Tests fail with connection errors

Ensure Docker services are running:

```bash
docker compose ps
```

Unit tests should not require Docker. If unit tests fail with connection errors, check that the test is not accidentally importing integration fixtures.
