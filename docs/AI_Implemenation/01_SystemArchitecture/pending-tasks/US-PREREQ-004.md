# US-PREREQ-004: Enable WebSocket Support for Local Development

| Field | Value |
|-------|-------|
| **Type** | 🏗️ Infrastructure Pre-Requisite |
| **Priority** | 🟡 HIGH — Unblocks US-PEND-030 |
| **Depends On** | US-PREREQ-002 (Redis) — Redis pub/sub is required for multi-instance WebSocket broadcast |
| **Estimated Effort** | 10 minutes |
| **Unblocks** | US-PEND-030 (Multi-user real-time collaboration) |

---

## User Story

**As a** backend developer implementing real-time collaboration,
**I want** WebSocket support configured for local development,
**So that** I can test presence tracking, page locking, and live content updates without deploying to a cloud environment.

---

## Intent of Work

FastAPI has **built-in WebSocket support** via Starlette — no additional server, no additional process, no additional Docker container required. The same `uvicorn` process that serves HTTP requests also handles WebSocket connections. This pre-requisite documents the configuration and verification steps.

**Why FastAPI native WebSocket over alternatives:**
- **FastAPI WebSocket** vs Socket.IO: Zero additional server. Same JWT auth as REST endpoints. Same uvicorn process.
- **FastAPI WebSocket** vs Django Channels: No Redis channel layer required for single-worker dev. Redis pub/sub is only needed for multi-instance, which is handled by US-PREREQ-002.
- **FastAPI WebSocket** vs separate WebSocket server: No extra port, no CORS complexity, shared application state.

Architecture:
```
Browser/Client
    │
    │  ws://localhost:8000/ws/courses/{id}/collaborate?token=JWT
    │
    ▼
┌──────────────────────────────────────────┐
│  Uvicorn (single process, dev mode)      │
│                                          │
│  ┌─────────────┐  ┌───────────────────┐  │
│  │ HTTP routes  │  │ WebSocket routes  │  │
│  │ (port 8000)  │  │ (port 8000)       │  │
│  └─────────────┘  └────────┬──────────┘  │
│                            │              │
│                     Redis pub/sub         │
│                     (localhost:6379)      │
└──────────────────────────────────────────┘
```

---

## Configuration (Zero Additional Setup)

WebSocket works out of the box with FastAPI + Uvicorn. No Docker container to start. No port to open. No config to change. The only dependency is Redis (US-PREREQ-002) for the pub/sub layer that broadcasts messages across multiple workers when you scale beyond 1 instance.

### Verify Uvicorn Supports WebSocket

```powershell
# Uvicorn with standard install already includes websockets library
python -c "import websockets; print('websockets version:', websockets.__version__)"
# Expected: websockets version: 12.x or 13.x
```

If `websockets` is not installed:
```powershell
pip install websockets>=12.0
```

### Verify FastAPI WebSocket Routing

```python
# test_websocket_setup.py — verify FastAPI WebSocket support
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
import asyncio

app = FastAPI()

@app.websocket("/ws/test")
async def test_websocket(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_text()
    await websocket.send_text(f"echo: {data}")

# Test with TestClient
def test_ws():
    client = TestClient(app)
    with client.websocket_connect("/ws/test") as ws:
        ws.send_text("hello")
        response = ws.receive_text()
        assert response == "echo: hello"
        print("✅ WebSocket routing works")

test_ws()
```

---

## Verification — Full Stack

```powershell
# 1. Start Redis (required for pub/sub broadcasting)
docker run -d --name elearning-redis -p 6379:6379 redis:7-alpine

# 2. Start the app
$env:PYTHONPATH = "."
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# Expected log: "Uvicorn running on http://0.0.0.0:8000"
# WebSocket endpoints are available on the SAME port — no separate service.

# 3. Test WebSocket connection (using wscat or Python)
python -c "
import asyncio
import websockets

async def test():
    async with websockets.connect('ws://localhost:8000/ws/test') as ws:
        await ws.send('hello')
        resp = await ws.recv()
        print(f'✅ WS Response: {resp}')

asyncio.run(test())
"
```

---

## Production Considerations (Not Required for Local Dev)

For production multi-worker deployment, the WebSocket layer needs:

| Concern | Dev (This Story) | Production |
|---------|-----------------|------------|
| Process | 1 uvicorn worker (`--reload`) | N uvicorn workers (`--workers 4`) |
| Broadcast | Works in single process | Needs Redis pub/sub (US-PREREQ-002) for cross-worker messages |
| Load Balancer | None needed | Sticky sessions (cookie-based) to pin client to same worker |
| Auth | JWT query param `?token=...` | Same or cookie-based for browser WebSocket API compatibility |

---

## Environment Variables (add to `.env`)

```bash
# WebSocket (no additional config needed for dev)
# Redis URL is used for pub/sub in multi-worker mode
REDIS_URL=redis://localhost:6379/0
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | `websockets` package installed | `python -c "import websockets; print(websockets.__version__)"` |
| AC-2 | FastAPI WebSocket routing test passes | `python test_websocket_setup.py` → ✅ |
| AC-3 | App starts with WebSocket routes registered | `uvicorn app.main:app` → no errors |
| AC-4 | Browser/CLI can connect to WebSocket endpoint | `wscat -c ws://localhost:8000/ws/test` → connects |

---

## Stories Unblocked

| Story | What It Needs WebSocket For |
|-------|---------------------------|
| **US-PEND-030** | `ws://localhost:8000/ws/courses/{id}/collaborate` — real-time presence, page locking, content change broadcasting |
