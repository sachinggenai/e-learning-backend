# KT: E-Learning Backend — Local Development Service Startup

**Audience:** DevOps Engineer building unified start/stop scripts (Bash + PowerShell)
**Date:** 2026-06-28
**Branch:** `AI-Architecture-update`

---

## 1. Service Inventory & Default Ports

### Tier 0 — Infrastructure (Docker containers, must start first)

| # | Service | Container Image | Default Port(s) | Protocol | Env Var |
|---|---------|----------------|-----------------|----------|---------|
| 1 | **PostgreSQL 16 + pgvector** | `pgvector/pgvector:pg16` | **5432** | TCP (asyncpg) | `POSTGRES_PORT` / `DATABASE_URL` |
| 2 | **Redis 7** | `redis:7-alpine` | **6379** | TCP (redis-py) | `REDIS_URL` |
| 3 | **Redpanda** (Kafka-compatible) | `docker.redpanda.com/redpandadata/redpanda:v24.1.1` | **19092** (Kafka API), **18082** (HTTP Proxy), **19644** (Admin, mapped from 9644) | TCP | `KAFKA_BOOTSTRAP_SERVERS` |
| 4 | **MinIO** (S3-compatible) | `minio/minio:latest` | **9000** (S3 API), **9001** (Console) | HTTP | `S3_ENDPOINT` |

**Compose file:** `docker-compose.yml` (project root)
**Volumes (persistent):** `pgdata`, `redisdata`, `rpdata`, `miniodata`

### Tier 1 — Main Application

| # | Service | Command | Default Port | Protocol | Env Var |
|---|---------|---------|-------------|----------|---------|
| 5 | **FastAPI Backend** | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` | **8000** | HTTP | `PORT` |

- **Entry point:** `app/main.py` → `app:app` (FastAPI instance)
- **PYTHONPATH must be set** to project root so `app` package resolves
- **Virtual environment:** `.venv/` in project root (created if missing by existing scripts)
- **API base path:** `/api/v1/`
- **Health check:** `GET /api/v1/health`
- **Docs:** `/api/v1/docs` (Swagger), `/api/v1/redoc` (ReDoc)
- **Metrics:** `GET /metrics` (Prometheus, if `prometheus-client` installed)

### Tier 2 — MCP Protocol Adapters (Optional, same-codebase supplementary services)

| # | Service | Uvicorn Target | Default Port | File |
|---|---------|---------------|-------------|------|
| 6 | **content-writer-mcp** | `app.mcp.content_writer.server:app` | **8001** | `app/mcp/content_writer/server.py` |
| 7 | **safety-scan-mcp** | `app.mcp.safety_scan.server:app` | **8002** | `app/mcp/safety_scan/server.py` |
| 8 | **template-registry-mcp** | `app.mcp.template_registry.server:app` | **8003** | `app/mcp/template_registry/server.py` |

- Each is a thin FastAPI wrapper translating MCP JSON-RPC to the existing `app.services.ai.*` Python service layer
- They share the same venv, PYTHONPATH, and dependency tree as the main application — NOT independent microservices
- They use lazy initialization: services are only instantiated when a tool is called, not at import time
- NOT required for basic app operation — only for AI-authoring MCP tool workflows

---

## 2. Strict Startup Order

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Docker Infrastructure (docker compose up -d)           │
│  ├── postgres:5432    ← MUST be healthy before Step 2           │
│  ├── redis:6379       ← can start in parallel                   │
│  ├── redpanda:19092   ← can start in parallel                   │
│  └── minio:9000       ← can start in parallel                   │
│                                                                 │
│  Wait for: PostgreSQL health check passes                       │
│  Health check: pg_isready -U elearning -d elearning_db          │
│  Timeout: 60s (30 attempts × 2s)                                │
├─────────────────────────────────────────────────────────────────┤
│  STEP 2: Database Migrations (alembic upgrade head)             │
│  Run unconditionally — idempotent, <1s if no pending changes.   │
│  (AUTO_MIGRATE flag is for production start.sh, not local dev)  │
├─────────────────────────────────────────────────────────────────┤
│  STEP 3: FastAPI Application                                    │
│  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload       │
│  (Auto-starts EmbeddingWorker + WorkflowOrchestrator as bg)     │
├─────────────────────────────────────────────────────────────────┤
│  STEP 4: MCP Servers (optional, can start in parallel)          │
│  ├── content-writer-mcp  :8001                                  │
│  ├── safety-scan-mcp     :8002                                  │
│  └── template-registry-mcp :8003                                │
└─────────────────────────────────────────────────────────────────┘
```

**Why this order:**
- Postgres MUST be accepting connections before Alembic runs
- Alembic MUST complete before FastAPI imports ORM models and calls `Base.metadata.create_all()` in its lifespan
- The app's lifespan also seeds component types and template types — these need tables to exist
- Redis/Redpanda/MinIO are soft dependencies: the app starts without them but some features degrade
- MCP servers are fully independent and can start any time after the app

---

## 3. Port Conflict / Already-Running Detection

### What "already running" means per service type

| Service Type | Detection Method | Kill/Restart Approach |
|---|---|---|
| **Docker containers** | `docker compose ps` — check container status + health | `docker compose down` then `docker compose up -d` |
| **Python/uvicorn** (port-based) | TCP socket probe on the port | Kill the process holding the port, then restart |
| **Alembic** | Idempotent — `alembic upgrade head` is a no-op if already at head | Just run it; it's safe |

### Port detection strategy (cross-platform)

**Windows (PowerShell):**
```powershell
# Check if port is in use
$conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($conn) {
    $proc = Get-Process -Id $conn.OwningProcess
    Write-Host "Port $Port in use by PID $($proc.Id) ($($proc.ProcessName))"
    Stop-Process -Id $proc.Id -Force
    Start-Sleep -Seconds 2
}
```

**Linux/macOS (Bash):**
```bash
# Check if port is in use, kill what's on it
PID=$(lsof -ti :$PORT 2>/dev/null)
if [ -n "$PID" ]; then
    echo "Port $PORT in use by PID $PID"
    kill -9 $PID 2>/dev/null
    sleep 1
fi
```

### Docker container health check pattern
```bash
# PostgreSQL health — blocks until ready or timeout
for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U elearning -d elearning_db 2>/dev/null; then
        echo "PostgreSQL ready"
        break
    fi
    [ $i -eq 30 ] && echo "ERROR: PostgreSQL did not become healthy" && exit 1
    sleep 2
done
```

---

## 4. Existing Scripts (What NOT to Duplicate)

These already exist — the new unified script should **orchestrate** them, not replace them:

| Script | What It Does | When to Call |
|--------|-------------|--------------|
| `docker/setup.sh` | Starts all 4 Docker containers, waits for health, verifies pgvector, runs migrations, verifies Redis/Redpanda/MinIO, creates MinIO bucket | **At infrastructure startup** |
| `run_dev.sh` / `run_dev.ps1` | Creates .venv if missing, installs deps if needed, probes port, sets PYTHONPATH, launches uvicorn --reload | **To start the FastAPI app** |

### What's MISSING (what the new script must add):

1. **Unified orchestration** — no single command starts infrastructure → migrations → app → MCP servers
2. **Port conflict resolution for Docker** — no script checks if container ports are already bound by something else
3. **MCP server launcher** — no script starts the 3 MCP servers
4. **Graceful stop-all** — `docker/setup.sh` has no corresponding teardown that also stops uvicorn and MCPs
5. **PowerShell parity** — `docker/setup.sh` is bash-only; no PS equivalent exists
6. **Health check aggregation** — no script verifies the full stack is healthy end-to-end

---

## 5. Target Script Design (What To Build)

### Script names (suggested)

| Script | Platform | Purpose |
|--------|----------|---------|
| `start-all.sh` | Bash (Linux/macOS/Git Bash) | Start everything in order |
| `start-all.ps1` | PowerShell (Windows) | Start everything in order |
| `stop-all.sh` | Bash | Graceful stop of everything |
| `stop-all.ps1` | PowerShell | Graceful stop of everything |

### `start-all` behavior spec

```
start-all.sh [--skip-docker] [--skip-mcp] [--app-port 8000]

1. DETECT environment (docker available? python/venv present?)
2. CHECK each port before starting:
   - 5432, 6379, 19092, 9000 → if Docker container with that port mapping exists, restart it
   - 8000, 8001, 8002, 8003 → if process on port, kill it
3. START Docker infrastructure (unless --skip-docker)
   a. docker compose up -d (all 4 containers)
   b. Wait for PostgreSQL healthy (pg_isready)
   c. Verify Redis PING
   d. Create MinIO bucket (idempotent)
4. RUN migrations: alembic upgrade head (or skip if AUTO_MIGRATE=true)
5. START FastAPI: uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8000} --reload
   (In background with log file, or foreground as last step)
6. START MCP servers (unless --skip-mcp):
   - uvicorn app.mcp.content_writer.server:app --port 8001 &
   - uvicorn app.mcp.safety_scan.server:app --port 8002 &
   - uvicorn app.mcp.template_registry.server:app --port 8003 &
7. PRINT summary table of all services + ports + health status
```

### `stop-all` behavior spec

```
stop-all.sh

1. STOP MCP servers (kill processes on ports 8001, 8002, 8003)
2. STOP FastAPI (kill process on port 8000)
3. STOP Docker containers: docker compose down
   (Optionally: docker compose down -v to also remove volumes)
4. VERIFY all ports are free
```

---

## 6. Key Technical Details

### 6.1 PostgreSQL credentials (from docker-compose.yml)
```
Host:     localhost
Port:     5432
User:     elearning
Password: elearning_secret
Database: elearning_db
URL:      postgresql+asyncpg://elearning:elearning_secret@localhost:5432/elearning_db
```

### 6.2 MinIO credentials (from docker-compose.yml)
```
Endpoint:  http://localhost:9000
Console:   http://localhost:9001
Access Key: minioadmin
Secret Key: minioadmin
Bucket:     elearning-assets
```

### 6.3 Virtual environment
```
Location:  <project_root>/.venv/
Python:    .venv/Scripts/python.exe (Windows) or .venv/bin/python (POSIX)
Packages:  pip install -r requirements.txt
```

### 6.4 Required environment variables (set before uvicorn)
```bash
# Must be set
PYTHONPATH=<project_root>

# Optionally loaded from .env file
ENVIRONMENT=development
DATABASE_URL=postgresql+asyncpg://elearning:elearning_secret@localhost:5432/elearning_db
REDIS_URL=redis://localhost:6379/0
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
S3_ENDPOINT=http://localhost:9000
CORS_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:5173
AUTO_MIGRATE=true
AI_AUTHORING_ENABLED=false
```

### 6.5 Dependencies between services

```
PostgreSQL ◄── Alembic ◄── FastAPI ◄── (optional) MCP servers
    │                          │
Redis ◄────────────────────────┘ (caching, rate limiting, WebSocket collab)
    │
Redpanda ◄─────────────────────┘ (event streaming — US-PEND-024)
    │
MinIO ◄────────────────────────┘ (SCORM/asset storage — Phase 0.5)
```

- **Hard dependency:** PostgreSQL MUST be up. App will fail to start without it.
- **Soft dependencies:** Redis, Redpanda, MinIO. App starts but degrades gracefully if they're down.
- **MCP servers:** Fully independent. Can start before or after the main app.

### 6.6 Background workers inside FastAPI

When the FastAPI app starts (via its `lifespan`), it conditionally launches background tasks based on feature flags:

| Worker | Feature Flag | Config Env Vars | What It Does |
|--------|-------------|----------------|--------------|
| **WorkflowOrchestrator** | `FEATURE_DURABLE_WORKFLOW_ENGINE` | `WORKFLOW_ENABLED`, `WORKFLOW_POLL_INTERVAL`, `WORKFLOW_MAX_CONCURRENCY` | Polls PostgreSQL for pending durable workflow jobs, executes state machine steps |
| **EmbeddingWorker** | `FEATURE_SIMILAR_COURSE_RETRIEVAL` | `EMBEDDING_PROVIDER`, `EMBEDDING_WORKER_INTERVAL` | Generates vector embeddings for courses using sentence-transformers or OpenAI |

These are auto-started and auto-stopped with the FastAPI lifespan — no separate script needed. In the default `.env`, both feature flags are **disabled** (`false`), so neither worker runs unless explicitly enabled.

---

## 7. Error Handling & Edge Cases

### What the script must handle:

| Scenario | Expected Behavior |
|----------|------------------|
| Docker not installed | Print clear error: "Docker required. Install from https://docker.com" |
| Docker not running | Print: "Docker daemon not running. Start Docker Desktop first." |
| Port already bound to another app | Kill the occupying process, warn user, restart |
| Port already bound to THIS app | No-op (skip, already running) |
| PostgreSQL slow to start | Retry up to 60s (30 × 2s), then fail with "PostgreSQL not healthy" |
| Alembic already at head | Safe — `alembic upgrade head` is idempotent |
| .venv missing | Create it, install requirements.txt |
| uvicorn not installed | pip install -r requirements.txt |
| .env file present | Source/load it before starting |
| User presses Ctrl+C | Trap SIGINT/SIGTERM, gracefully stop all services in reverse order |
| MCP server fails to start | Warn but continue — they're optional |

---

## 8. Verification / Smoke Test After Startup

After the script completes, verify with:

```bash
# 1. Docker containers all healthy
docker compose ps

# 2. FastAPI health endpoint
curl -s http://localhost:8000/api/v1/health | jq .

# 3. OpenAPI docs accessible
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/docs
# Expected: 200

# 4. PostgreSQL directly
docker compose exec postgres psql -U elearning -d elearning_db -c "SELECT 1"

# 5. Redis
docker compose exec redis redis-cli ping
# Expected: PONG

# 6. MinIO health
curl -s http://localhost:9000/minio/health/live
# Expected: (empty 200)

# 7. MCP servers (if started)
curl -s http://localhost:8001/docs  # content-writer-mcp
curl -s http://localhost:8002/docs  # safety-scan-mcp
curl -s http://localhost:8003/docs  # template-registry-mcp
```

---

## 9. Quick Reference Card

```
┌──────────────────────────────────────────────────────────────┐
│                    E-LEARNING BACKEND                         │
│                  Local Dev Quick Start                        │
├────────┬─────────┬───────────────────────────────────────────┤
│ PORT   │ SERVICE │ HOW TO CHECK                              │
├────────┼─────────┼───────────────────────────────────────────┤
│ 5432   │ PG 16   │ pg_isready -U elearning -d elearning_db   │
│ 6379   │ Redis 7 │ redis-cli ping                            │
│ 19092  │ Kafka   │ rpk cluster health (inside container)       │
│ 19644  │ Redpanda│ Admin API (mapped from container port 9644)  │
│ 9000   │ MinIO   │ curl localhost:9000/minio/health/live     │
│ 9001   │ MinIO   │ Browser: http://localhost:9001            │
│ 8000   │ FastAPI │ curl localhost:8000/api/v1/health         │
│ 8001   │ MCP-CW  │ curl localhost:8001/docs                  │
│ 8002   │ MCP-SS  │ curl localhost:8002/docs                  │
│ 8003   │ MCP-TR  │ curl localhost:8003/docs                  │
├────────┴─────────┴───────────────────────────────────────────┤
│ Start:  bash start-all.sh    or   .\start-all.ps1            │
│ Stop:   bash stop-all.sh     or   .\stop-all.ps1             │
│ Status: docker compose ps && curl localhost:8000/api/v1/health│
└──────────────────────────────────────────────────────────────┘
```

---

## 10. Files Reference (paths relative to project root)

| File | Role |
|------|------|
| `docker-compose.yml` | Defines all 4 infrastructure containers |
| `.env` / `.env.example` | Environment variables (loaded by python-dotenv in `app/db/config.py`) |
| `app/main.py` | FastAPI app factory + lifespan (startup/shutdown hooks) |
| `app/db/config.py` | Reads `.env` and builds DATABASE_URL |
| `app/services/ai/config.py` | AI subsystem configuration |
| `requirements.txt` | Python dependencies |
| `alembic.ini` | Alembic configuration |
| `alembic/` | Migration scripts |
| `docker/init-db.sql` | PostgreSQL init script (creates vector extension) |
| `docker/setup.sh` | Existing infra-only setup (bash) |
| `run_dev.sh` | Existing app-only launcher (bash) |
| `run_dev.ps1` | Existing app-only launcher (PowerShell) |

---

**Prepared by:** AI/Backend Developer
**For:** DevOps Engineer — build `start-all.sh`, `start-all.ps1`, `stop-all.sh`, `stop-all.ps1`
