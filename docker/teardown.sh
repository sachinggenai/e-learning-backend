#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# DEPRECATED — Use project-root scripts instead:
#   bash stop-all.sh       Non-destructive stop (preserves data)
#   bash reset-all.sh      Destructive reset (deletes all data)
#
# This script runs 'docker compose down -v' which DELETES ALL DATA.
# It is kept for backward compatibility with CI/CD pipelines.
# ═══════════════════════════════════════════════════════════════════
# teardown.sh — Stop and remove all e-learning-backend infrastructure containers
# Usage: bash docker/teardown.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "══════════════════════════════════════════════"
echo "  e-Learning Backend — Infrastructure Teardown"
echo "══════════════════════════════════════════════"
echo ""

cd "$PROJECT_DIR"

echo "🛑 Stopping all services..."
docker compose -f docker-compose.yml down

echo ""
echo "🗑️  Removing volumes (data will be lost)..."
docker compose -f docker-compose.yml down -v

echo ""
echo "✅ All services stopped and volumes removed."
