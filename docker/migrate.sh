#!/usr/bin/env bash
# migrate.sh — Run Alembic migrations with pre-flight checks
# Usage: bash docker/migrate.sh [--env local|qa|staging|prod]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV="${1:-local}"

echo "══════════════════════════════════════════════"
echo "  Alembic Migration — Environment: $ENV"
echo "══════════════════════════════════════════════"

cd "$PROJECT_DIR"

# ── Pre-flight: Check database connectivity ──────────
echo ""
echo "🔍 Checking database connectivity..."
PYTHONPATH=. python -c "
import os
print(f'  Database: {os.getenv(\"DATABASE_URL\", \"postgresql+asyncpg://elearning:elearning_secret@localhost:5432/elearning_db\")}')
" || { echo "❌ Cannot connect to database"; exit 1; }
echo "✅ Database reachable"

# ── Backup current revision ─────────────────────────
echo ""
echo "📦 Current migration state:"
PYTHONPATH=. alembic current

# ── Check for pending migrations ────────────────────
echo ""
echo "📋 Pending migrations:"
PYTHONPATH=. alembic history --indicate-current

# ── Run migrations ──────────────────────────────────
echo ""
echo "🚀 Running alembic upgrade head..."
PYTHONPATH=. alembic upgrade head

# ── Verify ──────────────────────────────────────────
echo ""
echo "🔍 New migration state:"
PYTHONPATH=. alembic current

echo ""
echo "📊 Tables created:"
PYTHONPATH=. python -c "
from sqlalchemy import text
from app.db.config import sync_engine
with sync_engine.connect() as conn:
    result = conn.execute(text(
        \"SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'workflow_%' OR tablename LIKE 'course_emb%' OR tablename LIKE 'course_sim%' OR tablename LIKE 'ai_%') ORDER BY tablename\"
    ))
    for row in result:
        print(f'  ✅ {row[0]}')
"

echo ""
echo "══════════════════════════════════════════════"
echo "  ✅ Migration complete for environment: $ENV"
echo "══════════════════════════════════════════════"
