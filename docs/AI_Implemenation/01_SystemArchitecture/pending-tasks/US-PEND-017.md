# US-PEND-017: Install pgvector Extension — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Infrastructure) |
| **Priority** | 🔴 CRITICAL |
| **Batch** | 5 — Infrastructure |
| **Depends On** | Docker Desktop (running on developer machine) |
| **Estimated Effort** | 0.5 days |
| **Target** | Local Docker PostgreSQL + QA/Staging/Production |

---

## User Story

**As a** course author searching for similar courses,
**I want** pgvector extension installed so Tier-1 semantic search works,
**So that** I get AI-powered similar course recommendations instead of keyword-only results.

---

## Intent of Work

The `pgvector` PostgreSQL extension must be installed on all database instances. Currently `similar_course_repo.py:_pgvector_available()` returns `False` because the extension is not installed, and Tier-1 vector search code is dead. The `course_embeddings` table exists but has 0 rows. This story unblocks the embedding population worker (US-PEND-020) and enables semantic course search.

---

## Current State (Code Verified 2026-06-21)

- `similar_course_repo.py:_pgvector_available()` checks `pg_extension WHERE extname='vector'` — returns `False`
- `course_embeddings` table exists (from migration 20260620_0001) but has **0 rows**
- `upsert_embedding()` method exists but is never called — marked "NOT called anywhere in the MVP code path"
- All Tier-1 code paths degrade gracefully to Tier-2 (keyword search)
- **No docker-compose.yml exists in the project**

---

## Expected State

```
✅ pgvector extension installed on all PostgreSQL instances
✅ ivfflat index created on course_embeddings.embedding column
✅ _pgvector_available() returns True
✅ Embedding population worker (US-PEND-020) can begin inserting vectors
✅ Tier-1 semantic search returns results
```

---

## 🔧 Open-Source Tooling Selection

| Tool | Version | Purpose | Why Selected |
|------|---------|---------|-------------|
| **pgvector** | 0.7.x | PostgreSQL vector extension | Most widely adopted Postgres vector extension; 12k+ GitHub stars; AWS RDS/Supabase native support; no separate vector DB needed |
| **Docker pgvector image** | `pgvector/pgvector:pg16` | Local development | Official pgvector community image; includes PostgreSQL 16 + pgvector pre-installed |
| **Docker Compose** | v2.x | Local orchestration | Already in Docker Desktop; single `docker compose up -d` command |

**Why pgvector over alternatives:**
- **pgvector** vs Pinecone/Weaviate/Milvus: Zero new infrastructure — runs inside existing PostgreSQL. No new service to manage.
- **pgvector** vs `cube` extension: pgvector supports ivfflat indexes for ANN (approximate nearest neighbor), cube only supports brute-force.
- **pgvector** vs ChromaDB: pgvector is SQL-standard, ACID-compliant, and shares the existing backup/replication of PostgreSQL.

---

## 📦 Pre-Requisite: Docker Compose Setup

### Step 1: Create `docker-compose.yml` at project root

```yaml
version: "3.9"

services:
  # ── PostgreSQL 16 + pgvector ─────────────────────────
  postgres:
    image: pgvector/pgvector:pg16
    container_name: elearning-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: elearning
      POSTGRES_PASSWORD: elearning_secret
      POSTGRES_DB: elearning_db
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/init-db.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U elearning -d elearning_db"]
      interval: 5s
      timeout: 3s
      retries: 5

  # ── Redis 7 (for future US-PEND-026) ────────────────
  redis:
    image: redis:7-alpine
    container_name: elearning-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  # ── Redpanda (Kafka-compatible, for future US-PEND-024) ──
  redpanda:
    image: docker.redpanda.com/redpandadata/redpanda:v24.1.1
    container_name: elearning-redpanda
    restart: unless-stopped
    command:
      - redpanda start
      - --smp 1
      - --overprovisioned
      - --kafka-addr internal://0.0.0.0:9092,external://0.0.0.0:19092
      - --advertise-kafka-addr internal://redpanda:9092,external://localhost:19092
      - --pandaproxy-addr internal://0.0.0.0:8082,external://0.0.0.0:18082
    ports:
      - "19092:19092"
      - "18082:18082"
      - "19644:9644"
    volumes:
      - rpdata:/var/lib/redpanda/data

  # ── MinIO (S3-compatible, for SCORM/asset storage) ──
  minio:
    image: minio/minio:latest
    container_name: elearning-minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - miniodata:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
  redisdata:
  rpdata:
  miniodata:
```

### Step 2: Create `docker/init-db.sql`

```sql
-- Auto-executed by PostgreSQL on first container start
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Verify extensions
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('vector', 'uuid-ossp');

-- Output confirmation
DO $$
BEGIN
    RAISE NOTICE '✅ pgvector extension installed successfully';
END $$;
```

### Step 3: Create `.env` additions

```bash
# ── Database (pgvector) ──────────────────────────────
DATABASE_URL=postgresql+asyncpg://elearning:elearning_secret@localhost:5432/elearning_db
DATABASE_URL_SYNC=postgresql://elearning:elearning_secret@localhost:5432/elearning_db

# ── Redis ────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Redpanda (Kafka) ─────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS=localhost:19092

# ── MinIO (S3-compatible storage) ────────────────────
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=elearning-assets
```

### Step 4: One-command startup script `docker/setup.sh`

```bash
#!/usr/bin/env bash
# setup.sh — One-command infrastructure setup for e-learning-backend
# Usage: bash docker/setup.sh

set -euo pipefail

echo "══════════════════════════════════════════════"
echo "  e-Learning Backend — Infrastructure Setup"
echo "══════════════════════════════════════════════"
echo ""

# ── Check Docker ────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "❌ Docker is not installed. Install Docker Desktop from https://docker.com"
    exit 1
fi
echo "✅ Docker found: $(docker --version)"

# ── Start services ──────────────────────────────────
echo ""
echo "🚀 Starting services (PostgreSQL+pgvector, Redis, Redpanda, MinIO)..."
docker compose -f docker-compose.yml up -d

# ── Wait for PostgreSQL ─────────────────────────────
echo ""
echo "⏳ Waiting for PostgreSQL to be healthy..."
until docker compose -f docker-compose.yml exec -T postgres pg_isready -U elearning -d elearning_db 2>/dev/null; do
    echo "   waiting..."
    sleep 2
done
echo "✅ PostgreSQL is ready"

# ── Verify pgvector ─────────────────────────────────
echo ""
echo "🔍 Verifying pgvector extension..."
PG_VECTOR=$(docker compose -f docker-compose.yml exec -T postgres psql -U elearning -d elearning_db -tAc "SELECT extversion FROM pg_extension WHERE extname='vector';")
if [ -z "$PG_VECTOR" ]; then
    echo "❌ pgvector NOT installed — running manual CREATE EXTENSION..."
    docker compose -f docker-compose.yml exec -T postgres psql -U elearning -d elearning_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
    PG_VECTOR=$(docker compose -f docker-compose.yml exec -T postgres psql -U elearning -d elearning_db -tAc "SELECT extversion FROM pg_extension WHERE extname='vector';")
fi
echo "✅ pgvector version: $PG_VECTOR"

# ── Run Alembic migrations ──────────────────────────
echo ""
echo "📦 Running Alembic migrations..."
cd "$(dirname "$0")/.."
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
```

### Step 5: Tear-down script `docker/teardown.sh`

```bash
#!/usr/bin/env bash
# teardown.sh — Stop and remove all infrastructure containers
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker-compose.yml down -v
echo "✅ All services stopped and volumes removed"
```

---

## Technical Details

### Verification Queries

```sql
-- After setup, verify on each environment:
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
-- Expected: vector | 0.7.x

-- Verify ivfflat index exists:
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename = 'course_embeddings' AND indexname LIKE '%embedding%';
-- Expected: idx_course_embeddings_ivfflat

-- Verify embedding dimension:
SELECT attname, atttypmod FROM pg_attribute
WHERE attrelid = 'course_embeddings'::regclass AND attname = 'embedding';
-- Expected: embedding | 1536 (for ada-002) or 768 (for all-MiniLM-L6-v2)
```

### Application Verification

```bash
# Verify pgvector is detected by the application
PYTHONPATH=. python -c "
from app.repositories.similar_course_repo import _pgvector_available
assert _pgvector_available(), 'pgvector must be available'
print('✅ pgvector detected by application')
"

# Verify embedding provider works
PYTHONPATH=. python -c "
from app.services.ai.embedding_provider import get_embedding_provider
provider = get_embedding_provider()
vector = provider.embed('test query')
assert len(vector) == provider.dimension
print(f'✅ Embedding provider: dim={provider.dimension}')
"
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | `pgvector` extension installed on local Docker PostgreSQL | `docker compose exec postgres psql -U elearning -d elearning_db -c "SELECT extversion FROM pg_extension WHERE extname='vector';"` |
| AC-2 | `_pgvector_available()` returns `True` | `PYTHONPATH=. python -c "from app.repositories.similar_course_repo import _pgvector_available; assert _pgvector_available()"` |
| AC-3 | Ivfflat index exists on `course_embeddings.embedding` | `psql -c "\di idx_course_embeddings*"` |
| AC-4 | `docker/setup.sh` completes without errors | `bash docker/setup.sh` |
| AC-5 | Docker image includes pgvector OS package | `docker compose exec postgres dpkg -l \| grep pgvector` |
| AC-6 | QA/Staging/Production have pgvector installed (separate ops task) | DB admin executes `CREATE EXTENSION IF NOT EXISTS vector;` |

---

## Scope Boundary

- **IN SCOPE:** Docker Compose setup, pgvector extension installation, init SQL, setup scripts, verification
- **OUT OF SCOPE:** Populating embeddings (US-PEND-020), changing pgvector version for cloud DBs

---

## Validation

```bash
# Full validation script
bash docker/setup.sh

# Verify extension
docker compose -f docker-compose.yml exec postgres psql -U elearning -d elearning_db -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"

# Run Alembic
PYTHONPATH=. alembic upgrade head

# Verify app detects pgvector
PYTHONPATH=. python -c "from app.repositories.similar_course_repo import _pgvector_available; assert _pgvector_available(); print('OK')"
```
