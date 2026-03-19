#!/usr/bin/env bash
# Agent Pulsar — Start all services locally
#
# Usage:
#   ./scripts/start.sh          # Start everything
#   ./scripts/start.sh stop     # Stop everything
#   ./scripts/start.sh status   # Check service status
#
# Prerequisites:
#   - uv (Python package manager)
#   - Docker + Docker Compose
#   - .env file with AP_ANTHROPIC_API_KEY set

set -euo pipefail

# Ensure common binary paths are available
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PID_DIR="$ROOT_DIR/.pids"
LOG_DIR="$ROOT_DIR/.logs"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No color

log() { echo -e "${CYAN}[Agent Pulsar]${NC} $1"; }
ok()  { echo -e "${GREEN}  ✓${NC} $1"; }
err() { echo -e "${RED}  ✗${NC} $1"; }
warn(){ echo -e "${YELLOW}  !${NC} $1"; }

# --- Stop ---
stop_services() {
    log "Stopping Agent Pulsar..."

    if [ -d "$PID_DIR" ]; then
        for pidfile in "$PID_DIR"/*.pid; do
            [ -f "$pidfile" ] || continue
            pid=$(cat "$pidfile")
            name=$(basename "$pidfile" .pid)
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
                ok "Stopped $name (pid $pid)"
            fi
            rm -f "$pidfile"
        done
    fi

    docker compose down 2>/dev/null || true
    ok "Docker services stopped"
    log "All services stopped."
}

# --- Status ---
check_status() {
    log "Service status:"

    # Docker services
    if docker compose ps --status running 2>/dev/null | grep -q "redis"; then
        ok "Redis: running"
    else
        err "Redis: not running"
    fi
    if docker compose ps --status running 2>/dev/null | grep -q "postgres"; then
        ok "PostgreSQL: running"
    else
        err "PostgreSQL: not running"
    fi

    # Python services
    if [ -d "$PID_DIR" ]; then
    for pidfile in "$PID_DIR"/*.pid; do
        [ -f "$pidfile" ] || continue
        pid=$(cat "$pidfile")
        name=$(basename "$pidfile" .pid)
        if kill -0 "$pid" 2>/dev/null; then
            ok "$name: running (pid $pid)"
        else
            err "$name: not running (stale pid $pid)"
        fi
    done
    fi

    # Health check
    if curl -sf http://localhost:8100/health >/dev/null 2>&1; then
        ok "Supervisor API: healthy (http://localhost:8100)"
    else
        err "Supervisor API: not reachable"
    fi
}

# --- Start ---
start_services() {
    log "Starting Agent Pulsar..."

    # Preflight checks
    if ! command -v uv &>/dev/null; then
        err "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    if ! command -v docker &>/dev/null; then
        err "Docker not found. Install Docker Desktop: https://docker.com/get-started"
        exit 1
    fi
    if [ ! -f ".env" ]; then
        err ".env file not found. Run: cp .env.example .env && edit .env"
        exit 1
    fi
    # Check that at least one auth method is configured
    if ! grep -qE "AP_ANTHROPIC_API_KEY=sk-|AP_OPENAI_API_KEY=sk-|AP_GEMINI_API_KEY=AIza" .env 2>/dev/null; then
        warn "No LLM API key configured in .env"
        warn "Run the setup wizard for guided config: uv run python scripts/run_setup_wizard.py"
    fi

    mkdir -p "$PID_DIR" "$LOG_DIR"

    # 1. Docker services (Redis + PostgreSQL + OpenClaw)
    log "Starting Docker services..."
    docker compose up -d
    ok "Docker services started"

    # Wait for health
    log "Waiting for services to be healthy..."
    for i in $(seq 1 20); do
        if docker compose ps 2>/dev/null | grep -q "healthy"; then
            break
        fi
        sleep 1
    done
    ok "Redis + PostgreSQL healthy"

    # Wait for OpenClaw to be ready
    log "Waiting for OpenClaw..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:18789 >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done
    if curl -sf http://localhost:18789 >/dev/null 2>&1; then
        ok "OpenClaw running (http://localhost:18789)"
    else
        warn "OpenClaw may still be starting — check http://localhost:18789"
    fi

    # 2. Install dependencies (if needed)
    if [ ! -d ".venv" ]; then
        log "Installing dependencies..."
        uv sync --all-extras
        ok "Dependencies installed"
    fi

    # 3. Run database migrations
    log "Running database migrations..."
    uv run alembic upgrade head 2>&1 | tail -1
    ok "Database migrated"

    # 4. Start Supervisor
    log "Starting Supervisor (port 8100)..."
    uv run uvicorn agent_pulsar.supervisor.app:app \
        --host 0.0.0.0 --port 8100 \
        > "$LOG_DIR/supervisor.log" 2>&1 &
    echo $! > "$PID_DIR/supervisor.pid"
    ok "Supervisor started (pid $(cat "$PID_DIR/supervisor.pid"))"

    # 5. Start workers
    log "Starting workers..."
    uv run python scripts/run_worker.py email \
        > "$LOG_DIR/worker-email.log" 2>&1 &
    echo $! > "$PID_DIR/worker-email.pid"
    ok "Email Worker started (pid $(cat "$PID_DIR/worker-email.pid"))"

    uv run python scripts/run_worker.py research \
        > "$LOG_DIR/worker-research.log" 2>&1 &
    echo $! > "$PID_DIR/worker-research.pid"
    ok "Research Worker started (pid $(cat "$PID_DIR/worker-research.pid"))"

    uv run python scripts/run_worker.py general \
        > "$LOG_DIR/worker-general.log" 2>&1 &
    echo $! > "$PID_DIR/worker-general.pid"
    ok "General Worker started (pid $(cat "$PID_DIR/worker-general.pid"))"

    # Wait for supervisor to be ready
    log "Waiting for Supervisor API..."
    for i in $(seq 1 10); do
        if curl -sf http://localhost:8100/health >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    echo ""
    log "Agent Pulsar is running!"
    echo ""
    echo -e "  ${GREEN}Supervisor API:${NC}  http://localhost:8100"
    echo -e "  ${GREEN}OpenClaw UI:${NC}     http://localhost:18789"
    echo -e "  ${GREEN}Health check:${NC}    http://localhost:8100/health"
    echo ""
    echo -e "  ${CYAN}Connect Telegram:${NC}"
    echo "    1. Open http://localhost:18789 in your browser"
    echo "    2. Go to Channels > Telegram"
    echo "    3. Enter your Telegram bot token (get one from @BotFather)"
    echo "    4. Send a message to your bot — Agent Pulsar handles the rest"
    echo ""
    echo -e "  ${CYAN}Or submit a task directly:${NC}"
    echo "    curl -X POST http://localhost:8100/tasks \\"
    echo "      -H 'Content-Type: application/json' \\"
    echo "      -d '{\"user_id\": \"you\", \"conversation_id\": \"test\", \"intent\": \"research.summarize\", \"raw_message\": \"Research AI agents\", \"params\": {}, \"priority\": \"normal\"}'"
    echo ""
    echo -e "  ${CYAN}Stop everything:${NC}  ./scripts/start.sh stop"
    echo -e "  ${CYAN}View logs:${NC}        tail -f .logs/supervisor.log"
    echo ""
}

# --- Main ---
case "${1:-start}" in
    start)  start_services ;;
    stop)   stop_services ;;
    status) check_status ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        exit 1
        ;;
esac
