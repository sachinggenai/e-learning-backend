#!/usr/bin/env bash
# start-all.sh — Start all e-learning-backend services for local development
# ---------------------------------------------------------------------------
# Starts services in chronological order with health checks, port conflict
# resolution, and graceful Ctrl+C shutdown.
#
# Usage:
#   bash start-all.sh                           Start everything
#   bash start-all.sh --skip-docker             Skip Docker (containers already running)
#   bash start-all.sh --skip-mcp                Skip MCP protocol adapters
#   bash start-all.sh --with-mcp                Force MCP even if AI is disabled
#   bash start-all.sh --app-port 8100           Use custom port for FastAPI
#   bash start-all.sh --help                    Show this help
#
# Startup order:
#   Docker containers → PG health check → Redpanda health check →
#   Alembic migrations → MCP servers (bg) → FastAPI (foreground)
# ---------------------------------------------------------------------------
set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────
APP_HOST="${HOST:-0.0.0.0}"
APP_PORT="${PORT:-8000}"
MCP_PORTS=(8001 8002 8003)
MCP_MODULES=(
    "app.mcp.content_writer.server:app"
    "app.mcp.safety_scan.server:app"
    "app.mcp.template_registry.server:app"
)
MCP_NAMES=("content-writer-mcp" "safety-scan-mcp" "template-registry-mcp")

# MCP Core Infrastructure (LLM Gateway + Domain Tools) — Phase 1-4
GATEWAY_PORT=8004
GATEWAY_MODULE="app.mcp.llm_gateway.server:app"
GATEWAY_NAME="llm-gateway-mcp"
DOMAIN_PORT=8005
DOMAIN_MODULE="app.mcp.domain_tools.server:app"
DOMAIN_NAME="domain-tools-mcp"

SKIP_DOCKER=false
SKIP_MCP=false
FORCE_MCP=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
cd "$PROJECT_DIR"

# ── Colours ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Parse flags ───────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --skip-docker) SKIP_DOCKER=true; shift ;;
        --skip-mcp)    SKIP_MCP=true; shift ;;
        --with-mcp)    FORCE_MCP=true; shift ;;
        --app-port)    APP_PORT="$2"; shift 2 ;;
        --help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) echo "Unknown flag: $1 (use --help for usage)"; exit 1 ;;
    esac
done

# ── Helpers ────────────────────────────────────────────────────
log_info()  { printf "${GREEN}[start-all]${NC} %s\n" "$1"; }
log_warn()  { printf "${YELLOW}[start-all]${NC} %s\n" "$1"; }
log_error() { printf "${RED}[start-all]${NC} %s\n" "$1"; }
log_step()  { echo -e "\n${CYAN}${BOLD}▶ $1${NC}"; }

kill_stale_on_port() {
    local port="$1"
    local pid
    pid=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -z "$pid" ]; then
        return 0  # port is free
    fi
    local proc_name
    proc_name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
    log_warn "Port $port in use by $proc_name (PID $pid) — killing stale process"
    kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
    # Wait for port to free up
    for i in $(seq 1 10); do
        pid=$(lsof -ti ":$port" 2>/dev/null || true)
        if [ -z "$pid" ]; then
            log_info "Port $port freed"
            return 0
        fi
        sleep 0.5
    done
    log_error "Port $port could not be freed after 5s"
    return 1
}

wait_for_postgres() {
    log_info "Waiting for PostgreSQL to be healthy (timeout: 60s)..."
    for i in $(seq 1 30); do
        if docker compose -f docker-compose.yml exec -T postgres \
            pg_isready -U "${POSTGRES_USER:-elearning}" -d "${POSTGRES_DB:-elearning_db}" \
            2>/dev/null; then
            log_info "PostgreSQL is ready"
            return 0
        fi
        printf "   waiting... (%d/30)\r" "$i"
        sleep 2
    done
    echo ""
    log_error "PostgreSQL did not become healthy within 60 seconds"
    log_error "Check: docker compose -f docker-compose.yml logs postgres"
    return 1
}

wait_for_redpanda() {
    log_info "Waiting for Redpanda to be healthy (timeout: 60s)..."
    for i in $(seq 1 30); do
        if docker compose -f docker-compose.yml exec -T redpanda \
            rpk cluster health 2>/dev/null | grep -q "Healthy: true"; then
            log_info "Redpanda is ready"
            return 0
        fi
        printf "   waiting... (%d/30)\r" "$i"
        sleep 2
    done
    echo ""
    log_warn "Redpanda is still starting — Kafka features will be unavailable until it finishes"
    log_warn "Check: docker compose -f docker-compose.yml logs redpanda"
    return 0  # soft dependency — don't block startup
}

# ── Cleanup trap (Ctrl+C) ─────────────────────────────────────
MCP_PIDS=()
cleanup() {
    echo ""
    echo ""
    log_warn "Shutting down..."
    for pid in "${MCP_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
            log_info "Stopped MCP server (PID $pid)"
        fi
    done
    wait "${MCP_PIDS[@]}" 2>/dev/null || true
    log_info "FastAPI stopped (foreground process)"
    echo ""
    echo "══════════════════════════════════════════════"
    echo -e "  ${GREEN}✅ All Python services stopped${NC}"
    echo "  Docker containers are still running (data preserved)"
    echo "  To stop Docker:  bash stop-all.sh"
    echo "══════════════════════════════════════════════"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ═══════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════
echo ""
echo "══════════════════════════════════════════════"
echo "  e-Learning Backend — Startup"
echo "══════════════════════════════════════════════"
echo ""

# --- Verify we're in the right directory ---
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ] || [ ! -f "$PROJECT_DIR/app/main.py" ]; then
    log_error "This script must be run from the project root directory"
    log_error "Expected: docker-compose.yml and app/main.py"
    exit 1
fi

# --- Determine MCP startup ---
START_MCP=false
if [ "$FORCE_MCP" = true ]; then
    START_MCP=true
elif [ "$SKIP_MCP" = true ]; then
    START_MCP=false
else
    # Auto-detect from .env AI_AUTHORING_ENABLED
    if [ -f "$PROJECT_DIR/.env" ]; then
        AI_ENABLED=$(grep -E '^AI_AUTHORING_ENABLED\s*=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d ' "' || echo "false")
        if [ "${AI_ENABLED:-false}" = "true" ]; then
            START_MCP=true
        fi
    fi
fi

# ── Load .env early so health checks use correct credentials ──
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# ═══════════════════════════════════════════════════════════════
# STEP 0 — Port conflict resolution
# ═══════════════════════════════════════════════════════════════
log_step "Step 0: Resolving port conflicts..."

# Only check Python ports if Docker isn't handling them
if [ "$SKIP_DOCKER" = false ]; then
    log_info "Docker will manage ports 5432, 6379, 19092, 9000, 9001"
fi

# Kill stale processes on app ports
kill_stale_on_port "$APP_PORT" || exit 1
if [ "$START_MCP" = true ]; then
    for port in "${MCP_PORTS[@]}"; do
        kill_stale_on_port "$port" || true  # MCP failures are non-blocking
    done
fi
# Gateway + Domain Tools are core MCP infrastructure — always clean
kill_stale_on_port "$GATEWAY_PORT" || true
kill_stale_on_port "$DOMAIN_PORT" || true
log_info "Port check complete"

# ═══════════════════════════════════════════════════════════════
# STEP 1 — Docker infrastructure
# ═══════════════════════════════════════════════════════════════
if [ "$SKIP_DOCKER" = true ]; then
    log_step "Step 1: SKIPPED (--skip-docker)"
else
    log_step "Step 1: Starting Docker infrastructure..."

    if ! command -v docker &>/dev/null; then
        log_error "Docker is not installed. Install Docker Desktop from: https://docker.com"
        log_error "Or use --skip-docker if your infrastructure is already running elsewhere."
        exit 1
    fi

    if ! docker info &>/dev/null; then
        log_error "Docker daemon is not running. Start Docker Desktop first."
        log_error "Or use --skip-docker if your infrastructure is already running elsewhere."
        exit 1
    fi

    # Clean up orphaned containers from prior incomplete runs
    ORPHANS=$(docker ps -a --filter "name=elearning-" --format "{{.Names}}" 2>/dev/null || true)
    MANAGED=$(docker compose -f docker-compose.yml ps -a --format "{{.Names}}" 2>/dev/null || true)
    STALE=$(comm -23 <(echo "$ORPHANS" | sort) <(echo "$MANAGED" | sort) 2>/dev/null || true)
    if [ -n "$STALE" ]; then
        log_warn "Removing orphaned containers: $(echo "$STALE" | tr '\n' ' ')"
        echo "$STALE" | xargs -r docker rm -f 2>/dev/null || true
    fi

    # Check if containers already exist (stopped) or need creation
    EXISTING=$(docker compose -f docker-compose.yml ps -q postgres 2>/dev/null || true)
    if [ -n "$EXISTING" ]; then
        log_info "Containers exist — starting stopped containers..."
        docker compose -f docker-compose.yml start
    else
        log_info "Creating and starting containers..."
        docker compose -f docker-compose.yml up -d --remove-orphans
    fi

    # Wait for PostgreSQL (hard dependency)
    wait_for_postgres || exit 1

    # Wait for Redpanda (soft dependency — warn but continue)
    wait_for_redpanda

    log_info "All infrastructure containers running"
fi

# ═══════════════════════════════════════════════════════════════
# STEP 2 — Database migrations
# ═══════════════════════════════════════════════════════════════
log_step "Step 2: Running database migrations..."

# Ensure virtual environment exists
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    log_info "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Detect venv Python
if [ -f "$VENV_DIR/bin/python" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python"
elif [ -f "$VENV_DIR/Scripts/python.exe" ]; then
    VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
else
    log_error "Could not find Python in virtual environment at $VENV_DIR"
    exit 1
fi

# Verify Python version (requires 3.12+)
PY_VER=$("$VENV_PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
if [ "$(printf '%s\n' "3.11" "$PY_VER" | sort -V | head -1)" != "3.11" ]; then
    log_error "Python 3.11+ required, found: $PY_VER"
    "$VENV_PYTHON" --version
    exit 1
fi
log_info "Python version: $PY_VER"

# Install dependencies if uvicorn is missing
if ! "$VENV_PYTHON" -c "import uvicorn" 2>/dev/null; then
    log_info "Installing dependencies (this may take a minute)..."
    "$VENV_PYTHON" -m pip install --upgrade pip -q
    "$VENV_PYTHON" -m pip install -r requirements.txt -q
fi

# Install alembic if missing
if ! "$VENV_PYTHON" -c "import alembic" 2>/dev/null; then
    log_info "Installing alembic..."
    "$VENV_PYTHON" -m pip install alembic -q
fi

# Run migrations
export PYTHONPATH="$PROJECT_DIR"
if "$VENV_PYTHON" -m alembic upgrade head; then
    log_info "Migrations applied"
else
    log_error "Alembic migration failed — check your database connection"
    log_error "Database URL: ${DATABASE_URL:-from component vars}"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════
# STEP 3 — MCP protocol adapters (background)
# ═══════════════════════════════════════════════════════════════
if [ "$START_MCP" = true ]; then
    log_step "Step 3: Starting MCP protocol adapters (background)..."
    for i in "${!MCP_PORTS[@]}"; do
        port="${MCP_PORTS[$i]}"
        module="${MCP_MODULES[$i]}"
        name="${MCP_NAMES[$i]}"

        log_info "Starting $name on port $port..."
        "$VENV_PYTHON" -m uvicorn "$module" --host 0.0.0.0 --port "$port" &
        MCP_PIDS+=($!)
        sleep 0.5  # stagger startup to avoid port conflicts
    done
    log_info "MCP servers started (PIDs: ${MCP_PIDS[*]})"
else
    log_step "Step 3: MCP adapters SKIPPED (AI_AUTHORING_ENABLED=false, use --with-mcp to force)"
fi

# ═══════════════════════════════════════════════════════════════

	# ═══════════════════════════════════════════════════════════════
	# STEP 3a — MCP Core: LLM Gateway + Domain Tools
	# ═══════════════════════════════════════════════════════════════
	log_step "Step 3a: Starting MCP Core Infrastructure..."
	log_info "  LLM Gateway   (port $GATEWAY_PORT) — provider-agnostic LLM access"
	log_info "  Domain Tools  (port $DOMAIN_PORT) — 7 AI tools"

	"$VENV_PYTHON" -m uvicorn "$GATEWAY_MODULE" --host 0.0.0.0 --port "$GATEWAY_PORT" &
	MCP_PIDS+=($!)
	sleep 1.5

	"$VENV_PYTHON" -m uvicorn "$DOMAIN_MODULE" --host 0.0.0.0 --port "$DOMAIN_PORT" &
	MCP_PIDS+=($!)
	sleep 0.5

	log_info "MCP Core started (Gateway PID: ${MCP_PIDS[-2]}, Domain Tools PID: ${MCP_PIDS[-1]})"

# STEP 4 — FastAPI backend (foreground)
# ═══════════════════════════════════════════════════════════════
log_step "Step 4: Starting FastAPI backend..."

echo ""
echo "══════════════════════════════════════════════"
echo -e "  ${GREEN}✅ All services starting${NC}"
echo ""
echo "  PostgreSQL:  localhost:${POSTGRES_PORT:-5432}"
echo "  Redis:       localhost:6379"
echo "  Redpanda:    localhost:19092 (Kafka) | localhost:19644 (Admin)"
echo "  MinIO:       localhost:${S3_PORT:-9000} (API) | localhost:${S3_CONSOLE_PORT:-9001} (Console)"
echo "  Ollama:      localhost:11434 (qwen2.5:7b, phi3:mini, nomic-embed-text)"
echo ""
echo "  --- MCP Architecture ---"
echo "  LLM Gateway:  http://localhost:$GATEWAY_PORT/health"
echo "  Domain Tools: http://localhost:$DOMAIN_PORT/health"
echo "  FastAPI:     http://$APP_HOST:$APP_PORT"
echo "  API Docs:    http://$APP_HOST:$APP_PORT/api/v1/docs"
echo "  Health:      http://$APP_HOST:$APP_PORT/api/v1/health"
if [ "$START_MCP" = true ]; then
    for i in "${!MCP_PORTS[@]}"; do
        echo "  ${MCP_NAMES[$i]}: http://$APP_HOST:${MCP_PORTS[$i]}/health"
    done
fi
echo ""
echo "  Press Ctrl+C to stop all Python services"
echo "  (Docker containers will keep running — use stop-all.sh)"
echo "══════════════════════════════════════════════"
echo ""

# Start FastAPI in FOREGROUND (blocking)
exec "$VENV_PYTHON" -m uvicorn app.main:app \
    --host "$APP_HOST" \
    --port "$APP_PORT" \
    --reload \
    --log-level info
