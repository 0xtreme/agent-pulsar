# Agent Pulsar

Event-driven AI agent orchestration framework — distributed systems reliability for personal AI.

Agent Pulsar decomposes complex tasks into isolated, ephemeral sub-tasks, selects the cheapest model that can handle each one, and executes them with full credential isolation. You talk to it via Telegram (or any of 20+ channels through OpenClaw), and it handles the rest.

## Quick Start

### Prerequisites

| Tool | Install |
|------|---------|
| **Python 3.12+** | Installed automatically by uv |
| **uv** | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Docker Desktop** | [docker.com/get-started](https://docker.com/get-started) |
| **Anthropic API key** | [console.anthropic.com](https://console.anthropic.com) |

### 1. Clone and configure

```bash
git clone https://github.com/0xtreme/agent-pulsar.git
cd agent-pulsar
cp .env.example .env
```

Edit `.env` and set your Anthropic API key:

```bash
AP_ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 2. Start everything

```bash
./scripts/start.sh
```

This starts Redis, PostgreSQL, runs database migrations, launches the Supervisor (port 8100), and starts the Email and Research workers. All in one command.

### 3. Submit a task

```bash
curl -X POST http://localhost:8100/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "pavi",
    "conversation_id": "test-1",
    "intent": "research.summarize",
    "raw_message": "Research the latest trends in AI agent frameworks and email me a summary",
    "params": {},
    "priority": "normal"
  }'
```

You'll get back a `request_id`. The Supervisor decomposes this into sub-tasks (research + email), routes them to workers, and executes them.

### 4. Check status

```bash
curl http://localhost:8100/tasks/<request_id>
```

### 5. Stop

```bash
./scripts/start.sh stop
```

## How It Works

```
You (Telegram/Slack/...) --> OpenClaw --> Agent Pulsar Skill
                                              |
                                    Event Bus (Redis Streams)
                                              |
                                         Supervisor
                                        /    |    \
                                   Decompose  Route  Assign Model
                                              |
                                    Worker (Email/Research/Payroll/Calendar)
                                              |
                                         Result --> Back to you
```

1. **You send a message** via Telegram (or any channel OpenClaw supports)
2. **OpenClaw** receives it. The Agent Pulsar skill decides: simple task? Handle it directly. Complex/sensitive task? Route to Agent Pulsar.
3. **Supervisor** decomposes the request into a DAG of atomic sub-tasks
4. **Model Router** classifies each sub-task's complexity and picks the cheapest model (Haiku for simple, Sonnet for moderate, Opus for complex)
5. **Workers** execute each sub-task in isolation (hot/warm/cold tier depending on sensitivity)
6. **Results** flow back through the event bus to you

## Architecture

| Layer | What | How |
|-------|------|-----|
| **Chat** | OpenClaw (leveraged) | 20+ channels, conversation management, skills system |
| **Event Bus** | Redis Streams (built) | Durable, ordered messaging with consumer groups and DLQ |
| **Supervisor** | FastAPI (built) | Task decomposition, model routing, execution tier assignment |
| **Workers** | Ephemeral (built) | Stateless, single-task, isolated — zero cross-task memory |
| **Security** | Vault + Token Broker (built) | Scoped JWT tokens, credential isolation, one-time onboarding |
| **LLM Gateway** | LiteLLM (leveraged) | Unified API across Claude, GPT, Llama with cost tracking |

## Available Workers

| Worker | Tier | Capability | What it does |
|--------|------|-----------|--------------|
| **Email** | Hot (~100ms) | Simple | Drafts professional emails |
| **Research** | Warm (~1-2s) | Moderate | Researches topics, produces summaries |
| **Payroll** | Cold (~5-10s) | Complex | Payroll operations with full Docker isolation |
| **Calendar** | Hot (~100ms) | Simple | Calendar reads and event management |

## Available Task Types

Use these as the `intent` when submitting tasks:

| Intent | Worker | Description |
|--------|--------|-------------|
| `email.send` | Email | Send an email |
| `email.draft` | Email | Draft an email without sending |
| `research.summarize` | Research | Research a topic and summarize |
| `research.analyze` | Research | Deep analysis of a topic |
| `payroll.run` | Payroll | Run payroll for a company/period |
| `payroll.fetch_employees` | Payroll | Fetch employee list |
| `calendar.read` | Calendar | List calendar events |
| `calendar.create_event` | Calendar | Create a new event |

## Configuration

All settings use the `AP_` environment variable prefix. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `AP_ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `AP_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `AP_DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection |
| `AP_SUPERVISOR_PORT` | `8100` | Supervisor API port |
| `AP_DECOMPOSITION_MODEL` | `claude-opus-4-0-20250514` | Model for task decomposition |
| `AP_CLASSIFICATION_MODEL` | `claude-haiku-4-5-20250414` | Model for complexity classification |

See `.env.example` for the full list.

## Connecting OpenClaw (Telegram)

Agent Pulsar uses [OpenClaw](https://github.com/openclaw/openclaw) as the user-facing chat layer. To connect via Telegram:

1. **Install OpenClaw** following their [setup guide](https://github.com/openclaw/openclaw#quick-start)
2. **Copy the Agent Pulsar skill** into OpenClaw:
   ```bash
   cp -r skills/agent-pulsar/ <your-openclaw-dir>/skills/agent-pulsar/
   ```
3. **Connect Telegram** via the OpenClaw Control UI at `http://localhost:18789`
4. **Set the webhook URL** in your `.env`:
   ```bash
   AP_OPENCLAW_WEBHOOK_URL=http://localhost:18789/hooks/agent
   ```

Now when you send a complex task via Telegram, OpenClaw routes it through Agent Pulsar automatically.

## Managing Credentials (Config Portal)

For workers that need external API access (Xero, Google Calendar, etc.):

```bash
# Start the Config Portal
uv run uvicorn agent_pulsar.config_portal.app:app --port 8102

# Generate a one-time onboarding link
curl -X POST http://localhost:8102/api/links/generate \
  -H "Content-Type: application/json" \
  -d '{"user_id": "pavi", "service": "xero"}'
```

Open the returned URL in your browser, enter your API credentials. They're stored securely in Vault (or in-memory for dev mode).

## Useful Commands

```bash
./scripts/start.sh              # Start everything
./scripts/start.sh stop         # Stop everything
./scripts/start.sh status       # Check what's running

tail -f .logs/supervisor.log    # Watch supervisor logs
tail -f .logs/worker-email.log  # Watch email worker logs

curl http://localhost:8100/health   # Health check
```

## Project Structure

```
agent-pulsar/
  src/agent_pulsar/
    supervisor/       # Control plane: decomposition, routing, scheduling
    workers/          # Execution plane: email, research, payroll, calendar
    security/         # Vault client, Token Broker, credential providers
    config_portal/    # Web UI for credential onboarding
    event_bus/        # Redis Streams event bus abstraction
    persistence/      # PostgreSQL task state (SQLAlchemy + Alembic)
    schemas/          # Pydantic models for all events and enums
    config.py         # Centralized settings (AP_ prefix)
  docs/
    TRACKER.md        # Project status tracker
    requirements.md   # Full architecture spec
    design.md         # System design document
    api-spec.md       # HTTP API specification
    event-schema.md   # Event bus message schemas
    development-guide.md  # Developer setup guide
  scripts/
    start.sh          # One-command startup
    run_worker.py     # Individual worker launcher
  docker/
    payroll/Dockerfile  # Cold-tier payroll worker image
```

## Documentation

| Doc | Purpose |
|-----|---------|
| **This README** | User quickstart and overview |
| [TRACKER.md](docs/TRACKER.md) | Project status across all phases |
| [development-guide.md](docs/development-guide.md) | Developer setup, testing, contributing |
| [requirements.md](docs/requirements.md) | Full architecture and requirements spec |
| [design.md](docs/design.md) | System design and data flow diagrams |
| [api-spec.md](docs/api-spec.md) | HTTP API specification (Supervisor + Token Broker + Config Portal) |
| [event-schema.md](docs/event-schema.md) | Event bus message schemas |

## License

MIT
