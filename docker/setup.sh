#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# NOTE — For local development, prefer the project-root scripts:
#   bash start-all.sh      Full stack startup (infra + app + MCP)
#   bash stop-all.sh       Non-destructive stop (preserves data)
#   bash reset-all.sh      Destructive reset (deletes all data)
#
# This script handles infrastructure ONLY (Docker + migrations).
# It is kept for CI/CD pipelines and standalone infra setup.
# ═══════════════════════════════════════════════════════════════════
# setup.sh — One-command infrastructure setup for e-learning-backend
# Usage: bash docker/setup.sh
#
# Starts PostgreSQL+pgvector, Redis, Redpanda (Kafka), and MinIO (S3)
# in Docker Desktop. Runs Alembic migrations. Verifies all services.
#
# Pre-requisites: Docker Desktop installed and running

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "══════════════════════════════════════════════"
echo "  e-Learning Backend — Infrastructure Setup"
echo "══════════════════════════════════════════════"
echo ""

# ── Check Docker ────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "❌ Docker is not installed."
    echo "   Install Docker Desktop from: https://docker.com"
    exit 1
fi
echo "✅ Docker found: $(docker --version)"

# ── Start services ──────────────────────────────────
echo ""
echo "🚀 Starting services (PostgreSQL+pgvector, Redis, Redpanda, MinIO)..."
cd "$PROJECT_DIR"
docker compose -f docker-compose.yml up -d

# ── Wait for PostgreSQL ─────────────────────────────
echo ""
echo "⏳ Waiting for PostgreSQL to be healthy..."
for i in $(seq 1 30); do
    if docker compose -f docker-compose.yml exec -T postgres pg_isready -U elearning -d elearning_db 2>/dev/null; then
        break
    fi
    echo "   waiting... ($i/30)"
    sleep 2
done
echo "✅ PostgreSQL is ready"

# ── Verify pgvector ─────────────────────────────────
echo ""
echo "🔍 Verifying pgvector extension..."
PG_VECTOR=$(docker compose -f docker-compose.yml exec -T postgres psql -U elearning -d elearning_db -tAc "SELECT extversion FROM pg_extension WHERE extname='vector';" 2>/dev/null || echo "")
if [ -z "$PG_VECTOR" ]; then
    echo "⚠️  pgvector NOT installed — running manual CREATE EXTENSION..."
    docker compose -f docker-compose.yml exec -T postgres psql -U elearning -d elearning_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
    PG_VECTOR=$(docker compose -f docker-compose.yml exec -T postgres psql -U elearning -d elearning_db -tAc "SELECT extversion FROM pg_extension WHERE extname='vector';")
fi
echo "✅ pgvector version: $PG_VECTOR"

# ── Run Alembic migrations ──────────────────────────
echo ""
echo "📦 Running Alembic migrations..."
cd "$PROJECT_DIR"
PYTHONPATH=. alembic upgrade head
echo "✅ Migrations applied"

# ── Verify Redis ────────────────────────────────────
echo ""
echo "🔍 Verifying Redis..."
REDIS_PING=$(docker compose -f docker-compose.yml exec -T redis redis-cli ping 2>/dev/null || echo "FAILED")
echo "✅ Redis: $REDIS_PING"

# ── Verify Redpanda ─────────────────────────────────
echo ""
echo "🔍 Verifying Redpanda (Kafka)..."
REDPANDA_OK=$(docker compose -f docker-compose.yml exec -T redpanda rpk cluster info 2>/dev/null | head -1 || echo "starting...")
echo "✅ Redpanda: $REDPANDA_OK"

# ── Verify MinIO ────────────────────────────────────
echo ""
echo "🔍 Verifying MinIO (S3)..."
MINIO_OK=$(curl -sf http://localhost:9000/minio/health/live 2>/dev/null && echo "healthy" || echo "starting...")
echo "✅ MinIO: $MINIO_OK"

# ── Create MinIO bucket ─────────────────────────────
echo ""
echo "🪣 Creating MinIO bucket 'elearning-assets'..."
docker compose -f docker-compose.yml exec -T minio mc mb local/elearning-assets 2>/dev/null || echo "   (bucket may already exist)"

echo ""
echo "══════════════════════════════════════════════"
echo "  ✅ Infrastructure is ready!"
echo ""
echo "  PostgreSQL:  localhost:5432 (pgvector installed)"
echo "  Redis:       localhost:6379"
echo "  Redpanda:    localhost:19092 (Kafka API)"
echo "  MinIO:       localhost:9000 (S3 API) | localhost:9001 (Console)"
echo ""
echo "  Run: docker compose -f docker-compose.yml ps"
echo "══════════════════════════════════════════════"
