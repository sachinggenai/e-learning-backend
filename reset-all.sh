#!/usr/bin/env bash
# reset-all.sh — DESTRUCTIVE reset of all e-learning-backend services & data
# ---------------------------------------------------------------------------
# ⚠️  WARNING: This DELETES ALL DATA — database rows, Redis cache,
#              MinIO files, and Redpanda topics. Cannot be undone.
#
# For a non-destructive stop, use: bash stop-all.sh
#
# Usage:
#   bash reset-all.sh               Interactive — prompts for confirmation
#   bash reset-all.sh --force       Non-interactive (CI/CD, no prompt)
#   bash reset-all.sh --help        Show this help
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
APP_PORT="${PORT:-8000}"
MCP_PORTS=(8001 8002 8003)
FORCE=false

# ── Colours ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# ── Parse flags ───────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE=true; shift ;;
        --help)
            sed -n '2,14p' "$0"
            exit 0
            ;;
        *) echo "Unknown flag: $1 (use --help for usage)"; exit 1 ;;
    esac
done

# ── Helpers ────────────────────────────────────────────────────
log_info()  { echo -e "${GREEN}[reset-all]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[reset-all]${NC} $1"; }
log_error() { echo -e "${RED}[reset-all]${NC} $1"; }

# ═══════════════════════════════════════════════════════════════
# CONFIRMATION GATE
# ═══════════════════════════════════════════════════════════════
echo ""
echo -e "${RED}${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}${BOLD}║  ⚠️  DESTRUCTIVE RESET — ALL DATA WILL BE DELETED  ⚠️  ║${NC}"
echo -e "${RED}${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  This will PERMANENTLY DELETE:"
echo "    • All database tables and rows (PostgreSQL)"
echo "    • All cached data (Redis)"
echo "    • All uploaded files and exports (MinIO)"
echo "    • All message queue topics and messages (Redpanda)"
echo "    • All Docker volumes (pgdata, redisdata, rpdata, miniodata)"
echo ""
echo "  This CANNOT be undone."
echo ""

if [ "$FORCE" = true ]; then
    log_warn "--force flag set — skipping confirmation prompt"
else
    read -r -p "  Type 'delete everything' to confirm: " CONFIRM
    if [ "$CONFIRM" != "delete everything" ]; then
        echo ""
        log_info "Cancelled — nothing was deleted."
        echo "  For a non-destructive stop, use: bash stop-all.sh"
        exit 0
    fi
    echo ""
fi

# ═══════════════════════════════════════════════════════════════
# PHASE 1 — Stop all Python processes
# ═══════════════════════════════════════════════════════════════
log_info "Phase 1/3: Killing Python services..."
STOPPED=0
for port in "$APP_PORT" "${MCP_PORTS[@]}"; do
    pid=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        log_info "Killing process on port $port (PID $pid)"
        kill -9 "$pid" 2>/dev/null || true
        STOPPED=$((STOPPED + 1))
    fi
done
if [ "$STOPPED" -eq 0 ]; then
    log_info "No Python services were running"
else
    log_info "Killed $STOPPED Python process(es)"
fi
sleep 1

# ═══════════════════════════════════════════════════════════════
# PHASE 2 — Destroy Docker containers + volumes
# ═══════════════════════════════════════════════════════════════
log_info "Phase 2/3: Destroying Docker containers and volumes..."

if ! command -v docker &>/dev/null; then
    log_warn "Docker not found — skipping container teardown"
elif ! docker info &>/dev/null 2>&1; then
    log_warn "Docker daemon not running — skipping container teardown"
else
    cd "$PROJECT_DIR"
    if [ -f docker-compose.yml ]; then
        docker compose -f docker-compose.yml down -v
        log_info "Containers stopped and volumes DELETED"
    else
        log_warn "docker-compose.yml not found — skipping"
    fi
fi

# ═══════════════════════════════════════════════════════════════
# PHASE 3 — Verify clean state
# ═══════════════════════════════════════════════════════════════
log_info "Phase 3/3: Verifying clean state..."
ALL_CLEAN=true

for port in "$APP_PORT" "${MCP_PORTS[@]}"; do
    pid=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        log_error "Port $port still occupied by PID $pid"
        ALL_CLEAN=false
    fi
done

if [ "$ALL_CLEAN" = true ]; then
    echo ""
    echo "══════════════════════════════════════════════"
    echo -e "  ${GREEN}✅ Reset complete${NC}"
    echo ""
    echo "  All services:       STOPPED"
    echo "  All data:           DELETED"
    echo "  Docker volumes:     REMOVED"
    echo "  Python processes:   KILLED"
    echo ""
    echo "  Fresh start:  bash start-all.sh"
    echo "══════════════════════════════════════════════"
else
    echo ""
    log_error "Some resources could not be cleaned. Check the errors above."
    exit 1
fi
