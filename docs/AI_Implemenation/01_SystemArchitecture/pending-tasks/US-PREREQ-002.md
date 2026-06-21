# US-PREREQ-002: Deploy Redis via Docker for Local Development

| Field | Value |
|-------|-------|
| **Type** | 🏗️ Infrastructure Pre-Requisite |
| **Priority** | 🔴 CRITICAL — Unblocks US-PEND-026, US-PEND-030 |
| **Depends On** | Docker Desktop (running on developer machine) |
| **Estimated Effort** | 5 minutes |
| **Unblocks** | US-PEND-026 (Redis cache layer), US-PEND-030 (WebSocket collaboration via Redis pub/sub) |

---

## User Story

**As a** backend developer implementing caching and real-time features,
**I want** a Redis instance running locally in Docker,
**So that** I can develop and test Redis caching, pub/sub broadcasting, and session storage without a remote instance.

---

## Intent of Work

Deploy **Redis 7 Alpine** — the official, minimal-footprint Redis image (~30MB). Redis serves dual purpose in this project: (1) **cache layer** for page reads with TTL-based invalidation (US-PEND-026), and (2) **pub/sub broker** for multi-instance WebSocket broadcasting (US-PEND-030).

**Why Redis over alternatives:** Redis combines caching + pub/sub in a single process. No separate message broker needed for real-time collaboration.

---

## Docker Deployment

### One-Command Install

```powershell
# PowerShell — run directly on Windows
docker run -d `
  --name elearning-redis `
  --restart unless-stopped `
  -p 6379:6379 `
  -v redis_data:/data `
  redis:7-alpine `
  redis-server --save 60 1 --loglevel notice
```

### What Each Flag Means

| Flag | Value | Purpose |
|------|-------|---------|
| `-p 6379:6379` | Default Redis port | Connect your app to `localhost:6379` |
| `-v redis_data:/data` | Persistent volume | Survives container restart — RDB snapshots stored here |
| `--save 60 1` | RDB persistence | Save snapshot every 60s if ≥1 key changed |
| `redis:7-alpine` | Alpine-based image | Minimal footprint (~30MB vs ~120MB for Debian) |

---

## Verification

```powershell
# 1. Check Redis is running
docker ps --filter name=elearning-redis

# 2. Ping (should return PONG)
docker exec elearning-redis redis-cli ping
# Expected: PONG

# 3. Set and get a key
docker exec elearning-redis redis-cli set test:key "hello elearning"
docker exec elearning-redis redis-cli get test:key
# Expected: "hello elearning"

# 4. Check persistence
docker exec elearning-redis redis-cli bgsave
docker exec elearning-redis redis-cli lastsave
# Expected: Unix timestamp

# 5. Check memory usage
docker exec elearning-redis redis-cli info memory | grep used_memory_human
# Expected: ~1MB (fresh instance)

# 6. Test pub/sub (Terminal 1 — subscriber)
docker exec -it elearning-redis redis-cli
# SUBSCRIBE elearning:test

# Terminal 2 — publisher
docker exec elearning-redis redis-cli publish elearning:test "hello from pubsub"
# Expected in Terminal 1: "hello from pubsub"
```

---

## Python Verification (After `pip install redis>=5.0.0`)

```python
# test_redis.py — verify Python → Redis connectivity
import asyncio
import redis.asyncio as redis

async def test_redis():
    # Basic get/set
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)

    await r.set("test:python", "working", ex=60)  # TTL 60s
    val = await r.get("test:python")
    assert val == "working", f"Expected 'working', got {val}"
    print(f"✅ Get/Set: {val}")

    # Ping
    pong = await r.ping()
    print(f"✅ Ping: {pong}")

    # Pub/sub
    pubsub = r.pubsub()
    await pubsub.subscribe("elearning:test")

    # Publish from a second connection
    r2 = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    await r2.publish("elearning:test", "pubsub_works")

    async for msg in pubsub.listen():
        if msg["type"] == "message":
            print(f"✅ Pub/Sub: {msg['data']}")
            break

    await pubsub.unsubscribe("elearning:test")
    await r.close()
    await r2.close()

asyncio.run(test_redis())
```

---

## Teardown

```powershell
# Stop and remove (data preserved in volume)
docker stop elearning-redis
docker rm elearning-redis

# Remove data volume (fresh start)
docker volume rm redis_data
```

---

## Environment Variables (add to `.env`)

```bash
# Redis
REDIS_URL=redis://localhost:6379/0
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Redis container running | `docker exec elearning-redis redis-cli ping` → PONG |
| AC-2 | Data persists across restart | Set key → `docker restart elearning-redis` → key still exists |
| AC-3 | Python async client connects | `redis.from_url("redis://localhost:6379/0")` → ping succeeds |
| AC-4 | Pub/sub works | Subscribe → publish → message received |

---

## Stories Unblocked

Once this pre-requisite is complete, these stories become implementable:

| Story | What It Needs Redis For |
|-------|------------------------|
| **US-PEND-026** | `CacheService` — cache `list_pages`/`fetch_page` with TTL, invalidate on update |
| **US-PEND-030** | `PresenceManager` — Redis sets for room presence, pub/sub for cross-worker broadcasting |
