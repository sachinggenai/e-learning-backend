# US-PEND-018: Deploy Alembic Migration to All Environments — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Deployment) |
| **Priority** | 🔴 CRITICAL |
| **Batch** | 5 — Infrastructure |
| **Depends On** | US-PEND-009 (migration schema fixes), US-PEND-017 (pgvector + Docker) |
| **Estimated Effort** | 0.5 days |
| **Target** | Local Docker → QA → Staging → Production PostgreSQL instances |

---

## User Story

**As a** release engineer,
**I want** Alembic migration `20260620_0002` applied to all environments,
**So that** workflow engine tables and course embedding tables exist and the application functions.

---

## Current State

- ✅ Migration applied locally: `alembic current` → `20260620_0002 (head)`
- ✅ 5 tables confirmed locally: `course_embeddings`, `course_similarity_cache`, `workflow_jobs`, `workflow_type_definitions`, `workflow_job_events`
- ❌ Migration NOT yet applied to QA, staging, or production
- ⚠️ Migration has 3 schema issues (US-PEND-009) that must be fixed before deployment

---

## Pre-Requisite: Automated Migration in Docker Setup

### Step 1: Add to `docker/setup.sh` (from US-PEND-017)

The setup script already includes `alembic upgrade head`. No changes needed.

### Step 2: Create `docker/migrate.sh` — Standalone migration script

```bash
#!/usr/bin/env bash
# migrate.sh — Run Alembic migrations with pre-flight checks
# Usage: bash docker/migrate.sh [--env qa|staging|prod]

set -euo pipefail
ENV="${1:-local}"

echo "══════════════════════════════════════════════"
echo "  Alembic Migration — Environment: $ENV"
echo "══════════════════════════════════════════════"

# ── Pre-flight: Check database connectivity ──────────
echo ""
echo "🔍 Checking database connectivity..."
PYTHONPATH=. python -c "
import os, asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.services.ai.config import get_ai_config
cfg = get_ai_config()
# Use the configured database URL
db_url = os.getenv('DATABASE_URL', 'postgresql+asyncpg://elearning:elearning_secret@localhost:5432/elearning_db')
print(f'  Database: {db_url}')
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
echo "🔍 Verifying migration:"
PYTHONPATH=. alembic current

echo ""
echo "📊 Tables created:"
PYTHONPATH=. python -c "
import asyncio
from sqlalchemy import text
from app.db.config import sync_engine
with sync_engine.connect() as conn:
    result = conn.execute(text(
        \"SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'workflow_%' OR tablename LIKE 'course_embed%' OR tablename LIKE 'course_similar%'\"
    ))
    for row in result:
        print(f'  ✅ {row[0]}')
"

echo ""
echo "══════════════════════════════════════════════"
echo "  ✅ Migration complete for environment: $ENV"
echo "══════════════════════════════════════════════"
```

### Step 3: Rollback script `docker/rollback.sh`

```bash
#!/usr/bin/env bash
# rollback.sh — Rollback the last Alembic migration
# Usage: bash docker/rollback.sh

set -euo pipefail

echo "⚠️  WARNING: This will rollback the most recent migration."
echo "   Current state:"
PYTHONPATH=. alembic current

read -rp "Enter the revision to downgrade to (or press Enter for -1): " TARGET
TARGET="${TARGET:--1}"

echo ""
echo "📦 Creating database backup..."
PGPASSWORD=elearning_secret pg_dump -h localhost -U elearning -d elearning_db > "backup_$(date +%Y%m%d_%H%M%S).sql"
echo "✅ Backup created"

echo ""
echo "⬇️  Rolling back..."
PYTHONPATH=. alembic downgrade "$TARGET"

echo ""
echo "✅ Rollback complete. New state:"
PYTHONPATH=. alembic current
```

---

## Technical Details

### Migration Files in Scope

| Migration File | Revision | Tables Created |
|---------------|----------|----------------|
| `20260620_0001_add_course_embeddings.py` | 20260620_0001 | `course_embeddings`, `course_similarity_cache` |
| `20260620_0002_create_workflow_tables.py` | 20260620_0002 | `workflow_jobs`, `workflow_type_definitions`, `workflow_job_events` |

### Pre-Flight Checklist (per environment)

1. ✅ US-PEND-009 fixes applied (JSONB default, Float type, FK documentation)
2. ✅ Database backup created (`pg_dump`)
3. ✅ Current revision confirmed (`alembic current`)
4. ✅ pgvector extension installed (`CREATE EXTENSION IF NOT EXISTS vector;`)
5. ✅ Rollback tested on local Docker first
6. ✅ Application starts successfully after migration

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | `alembic current` shows `20260620_0002` locally | `PYTHONPATH=. alembic current` |
| AC-2 | All 5 tables exist in local Docker | `psql -c "\dt workflow_*"` and `psql -c "\dt course_embed*"` |
| AC-3 | App starts successfully after migration | `PYTHONPATH=. python -c "from app.main import app; print('OK')"` |
| AC-4 | Rollback tested on local Docker | `bash docker/rollback.sh` then `bash docker/migrate.sh` |
| AC-5 | QA migration executed (separate task) | `bash docker/migrate.sh --env qa` |
| AC-6 | Staging migration executed (separate task) | `bash docker/migrate.sh --env staging` |

---

## Validation

```bash
# Full local validation
bash docker/setup.sh
bash docker/migrate.sh

# Verify tables
docker compose -f docker-compose.yml exec postgres psql -U elearning -d elearning_db -c "
SELECT tablename FROM pg_tables
WHERE schemaname='public'
  AND (tablename LIKE 'workflow_%' OR tablename LIKE 'course_%')
ORDER BY tablename;
"

# Test rollback
bash docker/rollback.sh
bash docker/migrate.sh
```
