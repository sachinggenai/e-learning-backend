#!/usr/bin/env bash
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
