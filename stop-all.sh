#!/usr/bin/env bash
# stop-all.sh — Gracefully stop all e-learning-backend services
# ---------------------------------------------------------------------------
# Preserves ALL data (database, cache, file storage, message queue).
# To also delete data, use reset-all.sh instead.
#
# Usage:
#   bash stop-all.sh              Stop everything
#   bash stop-all.sh --status     Show what's running (no stop)
#
# What it stops (in order):
#   1. MCP protocol adapters on ports 8001, 8002, 8003
#   2. FastAPI backend on port 8000 (or custom)
#   3. Docker infrastructure containers (postgres, redis, redpanda, minio)
# ---------------------------------------------------------------------------
set -euo pipefail

APP_PORT="${APP_PORT:-8000}"
MCP_PORTS=(8001 8002 8003)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"  # scripts live at project root

# ── Colours ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Colour

# ── Helpers ────────────────────────────────────────────────────
log_info()  { echo -e "${GREEN}[stop-all]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[stop-all]${NC} $1"; }
log_error() { echo -e "${RED}[stop-all]${NC} $1"; }

kill_port_process() {
    local port="$1"
    local label="$2"
    local pid

    pid=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -z "$pid" ]; then
        return 1  # nothing on this port
    fi

    log_info "Port $port occupied by PID $pid — stopping $label"
    kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true

    # Wait for the process to actually exit
    for i in $(seq 1 10); do
        if ! kill -0 "$pid" 2>/dev/null; then
            log_info "$label stopped (was PID $pid)"
            return 0
        fi
        sleep 0.5
    done

    # Force kill after 5s
    log_warn "$label did not exit gracefully — force-killing"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
    return 0
}

# ── Status-only mode ───────────────────────────────────────────
if [ "${1:-}" = "--status" ]; then
    echo ""
    echo "══════════════════════════════════════════════"
    echo "  e-Learning Backend — Running Services"
    echo "══════════════════════════════════════════════"
    echo ""
    echo "  Python processes:"
    for port in "$APP_PORT" "${MCP_PORTS[@]}"; do
        pid=$(lsof -ti ":$port" 2>/dev/null || true)
        if [ -n "$pid" ]; then
            proc_name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
            echo -e "    ${GREEN}●${NC} Port $port — PID $pid ($proc_name)"
        else
            echo -e "    ${RED}○${NC} Port $port — nothing"
        fi
    done
    echo ""
    echo "  Docker containers:"
    if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
        cd "$PROJECT_DIR"
        docker compose -f docker-compose.yml ps 2>/dev/null || echo "    No containers running"
    else
        echo "    Docker not available"
    fi
    echo ""
    exit 0
fi

# ═══════════════════════════════════════════════════════════════
# STOP PHASE 1 — MCP protocol adapters (ports 8001-8003)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "══════════════════════════════════════════════"
echo "  e-Learning Backend — Graceful Stop"
echo "══════════════════════════════════════════════"
echo ""

log_info "Phase 1/3: Stopping MCP protocol adapters..."
STOPPED_MCP=0
for port in "${MCP_PORTS[@]}"; do
    if kill_port_process "$port" "MCP server :$port"; then
        STOPPED_MCP=$((STOPPED_MCP + 1))
    fi
done
if [ "$STOPPED_MCP" -eq 0 ]; then
    log_info "No MCP servers were running"
else
    log_info "Stopped $STOPPED_MCP MCP server(s)"
fi

# ═══════════════════════════════════════════════════════════════
# STOP PHASE 2 — FastAPI backend (port 8000)
# ═══════════════════════════════════════════════════════════════
echo ""
log_info "Phase 2/3: Stopping FastAPI backend..."
if kill_port_process "$APP_PORT" "FastAPI backend :$APP_PORT"; then
    log_info "FastAPI backend stopped"
else
    log_info "FastAPI backend was not running on port $APP_PORT"
fi

# ═══════════════════════════════════════════════════════════════
# STOP PHASE 3 — Docker infrastructure containers
# ═══════════════════════════════════════════════════════════════
echo ""
log_info "Phase 3/3: Stopping Docker infrastructure..."

if ! command -v docker &>/dev/null; then
    log_warn "Docker not found — skipping container stop"
elif ! docker info &>/dev/null 2>&1; then
    log_warn "Docker daemon not running — skipping container stop"
else
    cd "$PROJECT_DIR"
    if [ -f docker-compose.yml ]; then
        docker compose -f docker-compose.yml stop
        log_info "Docker containers stopped (data preserved)"
    else
        log_warn "docker-compose.yml not found — skipping container stop"
    fi
fi

# ═══════════════════════════════════════════════════════════════
# VERIFY — All ports free
# ═══════════════════════════════════════════════════════════════
echo ""
log_info "Verifying all ports are free..."
ALL_FREE=true
for port in "$APP_PORT" "${MCP_PORTS[@]}"; do
    pid=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        log_error "Port $port STILL occupied by PID $pid"
        ALL_FREE=false
    fi
done

if [ "$ALL_FREE" = true ]; then
    echo ""
    echo "══════════════════════════════════════════════"
    echo -e "  ${GREEN}✅ All services stopped${NC}"
    echo ""
    echo "  App ports 8000-8003: FREE"
    echo "  Docker containers:   STOPPED (data preserved)"
    echo "  Database, cache, files: SAFE"
    echo ""
    echo "  Restart:  bash start-all.sh"
    echo "  Wipe all: bash reset-all.sh"
    echo "══════════════════════════════════════════════"
else
    echo ""
    log_error "Some ports could not be freed. You may need to:"
    log_error "  1. Manually kill the PIDs listed above"
    log_error "  2. Or run: bash reset-all.sh (destructive)"
    exit 1
fi
