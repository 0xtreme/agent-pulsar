# Agent Pulsar

Event-driven AI agent orchestration framework — distributed systems reliability for personal AI.

Agent Pulsar decomposes complex tasks into isolated, ephemeral sub-tasks, selects the cheapest model that can handle each one, and executes them with full credential isolation. You talk to it via Telegram (or any of 20+ channels through OpenClaw), and it handles the rest.

## Quick Start

### Prerequisites

| Tool | Install |
|------|---------|
| **Docker Desktop** | [docker.com/get-started](https://docker.com/get-started) — must be running |
| **Anthropic API key** OR **Google Cloud** OR **AWS** | See authentication options below |

That's it. Everything else is installed automatically.

### 1. Clone the repo

```bash
git clone https://github.com/0xtreme/agent-pulsar.git
cd agent-pulsar
```

### 2. Run the setup wizard (recommended)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # Install uv (if you don't have it)
source ~/.local/bin/env                              # Add uv to PATH
uv sync --all-extras                                 # Install dependencies
uv run python scripts/run_setup_wizard.py            # Start the wizard
```

Open **http://localhost:8103** in your browser. The wizard walks you through:
1. Prerequisite checks (Docker, Python, etc.)
2. Authentication setup (API key, Vertex AI, or Bedrock)
3. Starting services
4. Testing with your first task

### 2b. Manual setup (alternative)

If you prefer the command line:

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

# Install dependencies
uv sync --all-extras

# Configure
cp .env.example .env
# Edit .env — set your auth method (see "Authentication" below)

# Start everything
./scripts/start.sh
```

### 3. Submit a task

```bash
curl -X POST http://localhost:8100/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "you",
    "conversation_id": "test-1",
    "intent": "research.summarize",
    "raw_message": "Research the latest trends in AI agent frameworks",
    "params": {},
    "priority": "normal"
  }'
```

You'll get back a `request_id`. Check status:

```bash
curl http://localhost:8100/tasks/<request_id>
```

### 4. Stop

```bash
./scripts/start.sh stop
```

## Authentication

Agent Pulsar supports three LLM providers via [LiteLLM](https://github.com/BerriAI/litellm). Pick whichever you have a subscription or API key for:

### Option A: Anthropic (default)

```bash
AP_ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Get a key at [console.anthropic.com](https://console.anthropic.com). Uses Claude Haiku / Sonnet / Opus.

### Option B: OpenAI

```bash
AP_LLM_PROVIDER=openai
AP_OPENAI_API_KEY=sk-your-key-here
```

Get a key at [platform.openai.com](https://platform.openai.com/api-keys). Uses GPT-4o-mini / GPT-4o.

### Option C: Google Gemini

```bash
AP_LLM_PROVIDER=gemini
AP_GEMINI_API_KEY=AIza-your-key-here
```

Get a key at [aistudio.google.com](https://aistudio.google.com/apikey). Uses Gemini Flash / Pro.

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
                                         Worker executes task
                                              |
                                         Result --> Back to you
```

1. **You send a message** via Telegram (or any channel OpenClaw supports)
2. **OpenClaw** receives it. The Agent Pulsar skill decides: simple task? Handle it directly. Complex/sensitive task? Route to Agent Pulsar.
3. **Supervisor** decomposes the request into a DAG of atomic sub-tasks
4. **Model Router** classifies each sub-task's complexity and picks the cheapest model (Haiku for simple, Sonnet for moderate, Opus for complex)
5. **Workers** execute each sub-task in isolation (hot/warm/cold tier depending on sensitivity)
6. **Results** flow back through the event bus to you

## Dynamic Task Routing

You can ask Agent Pulsar to do **anything** — not just predefined task types. The system dynamically figures out what to do:

```bash
# These all work:
"Research quantum computing trends"          # → Research Worker
"Draft a thank you email to the team"        # → Email Worker
"Find me a pasta recipe for dinner"          # → General Worker (handles anything)
"Translate this document to Spanish"         # → General Worker
"Run payroll for March"                      # → Payroll Worker (cold tier, isolated)
```

Specialized workers handle known domains (email, research, payroll, calendar) with optimized prompts and execution tiers. Everything else routes to the **General Worker**, which uses Sonnet to handle any task dynamically.

## Workers

| Worker | Tier | Capability | What it does |
|--------|------|-----------|--------------|
| **General** | Hot (~100ms) | Moderate | Handles any task type dynamically |
| **Email** | Hot (~100ms) | Simple | Drafts professional emails |
| **Research** | Warm (~1-2s) | Moderate | Researches topics, produces summaries |
| **Payroll** | Cold (~5-10s) | Complex | Payroll operations with full Docker isolation |
| **Calendar** | Hot (~100ms) | Simple | Calendar reads and event management |

## Configuration

All settings use the `AP_` environment variable prefix. Only authentication is required — everything else has defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `AP_ANTHROPIC_API_KEY` | — | Anthropic API key (if using direct API) |
| `AP_LLM_PROVIDER` | `anthropic` | `anthropic`, `vertex_ai`, or `bedrock` |
| `AP_SUPERVISOR_PORT` | `8100` | Supervisor API port |
| `AP_DECOMPOSITION_MODEL` | `claude-opus-4-0-20250514` | Model for task decomposition |
| `AP_CLASSIFICATION_MODEL` | `claude-haiku-4-5-20250414` | Model for complexity classification |

See `.env.example` for the full list with all options.

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
  -d '{"user_id": "you", "service": "xero"}'
```

Open the returned URL in your browser, enter your API credentials. They're stored securely in Vault (or in-memory for dev mode).

## Useful Commands

```bash
./scripts/start.sh                # Start everything
./scripts/start.sh stop           # Stop everything
./scripts/start.sh status         # Check what's running

uv run python scripts/run_setup_wizard.py   # Setup wizard (http://localhost:8103)

tail -f .logs/supervisor.log      # Watch supervisor logs
tail -f .logs/worker-general.log  # Watch general worker logs

curl http://localhost:8100/health  # Health check
```

## Project Structure

```
agent-pulsar/
  src/agent_pulsar/
    supervisor/       # Control plane: decomposition, routing, scheduling
    workers/          # Execution plane: general, email, research, payroll, calendar
    security/         # Vault client, Token Broker, credential providers
    config_portal/    # Web UI for credential onboarding
    setup_wizard/     # Web-based setup guide for first-time users
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
    run_setup_wizard.py  # Setup wizard launcher
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
