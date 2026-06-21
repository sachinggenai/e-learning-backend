# Postman Collection Execution Guide — E-Learning AI Backend

**Collection:** `E-Learning_AI_Postman_Collection.json` (same directory)  
**Coverage:** All 14 flow charts, 169 endpoints, WebSocket collaboration test  
**Tests:** 1,058 automated tests also available (`PYTHONPATH=. python tests/run_*.py`)

---

## 1. IMPORT — Get the Collection into Postman

1. Open Postman → **File → Import** (or Ctrl+O)
2. Select `E-Learning_AI_Postman_Collection.json`
3. Collection appears with 16 folders

---

## 2. ENVIRONMENT — Set Variables

Create a Postman Environment or use Collection Variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `base_url` | `http://localhost:8000` | Backend API base URL |
| `ws_url` | `ws://localhost:8000` | WebSocket base URL |
| `token` | `test-user-001` | Mock auth token (user_id) |
| `course_id` | `COURSE-DEMO-001` | Target course for operations |
| `session_id` | *(auto-set)* | Populated by Flow 01 test script |
| `page_id` | *(auto-set)* | Populated by Flow 03 test script |
| `proposal_id` | *(auto-set)* | Populated by Flow 05 test script |
| `import_job_id` | *(auto-set)* | Populated by Flow 10 test script |
| `workflow_job_id` | *(auto-set)* | Populated by Workflow Engine test script |

---

## 3. PREREQUISITES — Before You Start

### Infrastructure (one-time)
```bash
# Start all services (PostgreSQL+pgvector, Redis, Redpanda, MinIO)
bash docker/setup.sh
```

### Application
```bash
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload
```

### Verify
```
GET {{base_url}}/api/v1/health → 200 OK
GET {{base_url}}/api/v1/ai/feature-status → ai_authoring_enabled: true
```

---

## 4. EXECUTION ORDER — Follow Exactly

The flows have dependencies. Run them in this order:

### Phase 1: Foundation (5 min)

| Step | Folder | Request | What It Does | Stores |
|------|--------|---------|--------------|--------|
| 1 | Prerequisites | Health Check | Verify server is up | — |
| 2 | Prerequisites | Check Feature Flags | Confirm AI features enabled | — |
| 3 | **Flow 01** | 01-Create AI Session | Create session scoped to user+course | `session_id` |
| 4 | Flow 01 | 02-Get Session | Verify session persisted | — |

### Phase 2: Context & Retrieval (3 min)

| Step | Folder | Request | What It Does | Stores |
|------|--------|---------|--------------|--------|
| 5 | **Flow 03** | 01-List Pages | Get page metadata for course | `page_id` |
| 6 | Flow 03 | 02-Fetch Page | Get full page content + components | — |
| 7 | **Flow 04** | 01-Query Similar Courses | Test 3-tier retrieval pipeline | — |
| 8 | Similar Courses | 01-Search Similar Courses | Direct API variant | — |

### Phase 3: Chat + Proposals (5 min)

| Step | Folder | Request | What It Does | Stores |
|------|--------|---------|--------------|--------|
| 9 | **Flow 02** | 01-Send Chat Message | Chat → plan → propose cycle | — |
| 10 | Flow 02 | 02-Chat History | Verify conversation stored | — |
| 11 | **Flow 05/06** | 01-Create Page Proposal | Full proposal creation | `proposal_id` |
| 12 | Flow 05/06 | 02-Get Proposal Details | Verify proposal stored | — |
| 13 | Flow 05/06 | 03-Apply Proposal | Apply with user_confirmed=true | — |
| 14 | Flow 05/06 | 04-List All Proposals | Query by session | — |

### Phase 4: Update + Delete (3 min)

| Step | Folder | Request | What It Does | Stores |
|------|--------|---------|--------------|--------|
| 15 | **Flow 07** | 01-Create Update Proposal | Update existing page | `proposal_id` |
| 16 | Flow 07 | 02-Apply Update Proposal | Apply update | — |
| 17 | **Flow 08** | 01-Propose Delete Page | Destructive delete proposal | `proposal_id` |
| 18 | Flow 08 | 02-Confirm Delete | Confirm + token validation | — |

### Phase 5: Validation + Export (2 min)

| Step | Folder | Request | What It Does |
|------|--------|---------|--------------|
| 19 | **Flow 09** | 01-Validate Course (AI Tool) | Full structural validation |
| 20 | Flow 09 | 02-Validate Export Readiness | SCORM export validation |
| 21 | **Flow 12-14** | 01-Export Course as SCORM | Generate SCORM package |
| 22 | Flow 12-14 | 02-Get Export Formats | List supported formats |

### Phase 6: File Ingestion (5 min)

| Step | Folder | Request | What It Does | Stores |
|------|--------|---------|--------------|--------|
| 23 | **Flow 10/11** | 01-Upload File | Upload .txt outline | `import_job_id` |
| 24 | Flow 10/11 | 02-Get Ingestion Job Status | Check extraction status | — |
| 25 | Flow 10/11 | 03-Propose Page Breakdown | AI segmentation | — |
| 26 | Flow 10/11 | 04-Review & Approve Plan | Approve page plan | — |
| 27 | Flow 10/11 | 05-Generate Full Course | Submit workflow job | `workflow_job_id` |
| 28 | Flow 10/11 | 06-Poll Generation Status | Check progress | — |

### Phase 7: Workflow Engine (5 min)

| Step | Folder | Request | What It Does |
|------|--------|---------|--------------|
| 29 | Workflow Engine | 01-Submit Course Generation | Submit direct workflow job |
| 30 | Workflow Engine | 02-Poll Workflow Status | Check state + progress |
| 31 | Workflow Engine | 03-Get Workflow Events | Event history |
| 32 | Workflow Engine | 05-List Workflow Jobs | All jobs with filter |
| 33 | Workflow Engine | 04-Cancel Workflow | Cancel running job |
| 34 | Workflow Engine | 06-Retry Failed Workflow | Retry failed job |

### Phase 8: Admin & Audit (2 min)

| Step | Folder | Request | What It Does |
|------|--------|---------|--------------|
| 35 | Admin & Audit | 01-Safety Events List | View safety violations |
| 36 | Admin & Audit | 02-Safety Statistics | Aggregate safety data |
| 37 | Admin & Audit | 03-Audit Logs | Query by session |
| 38 | Admin & Audit | 04-Audit Summary | Compliance summary |

### Phase 9: WebSocket (Manual Test)

| Step | Folder | Request | What It Does |
|------|--------|---------|--------------|
| 39 | WebSocket | See folder description | Real-time collaboration test (requires wscat CLI) |

### Phase 10: e2e Collection Runner

| Step | Folder | Request | What It Does |
|------|--------|---------|--------------|
| 40 | e2e TEST | Run entire folder | Automated full happy path in 30 seconds |

---

## 5. WEBSOCKET TEST — Manual Steps

The WebSocket endpoint cannot be tested in the Postman request builder. Use one of these methods:

### Option A: wscat CLI
```bash
npm install -g wscat

# Terminal 1 (User A)
wscat -c "ws://localhost:8000/ws/courses/COURSE-DEMO-001/collaborate?token=test-user-001"
# → {"event":"user_joined","data":{"user_id":"test-user-001",...}}

# Terminal 2 (User B — open a second terminal)
wscat -c "ws://localhost:8000/ws/courses/COURSE-DEMO-001/collaborate?token=test-user-002"
# → {"event":"user_joined","data":{"user_id":"test-user-002",...}}
# → Both terminals show both user_joined events

# In Terminal 1, send:
{"action": "ping"}
# → {"event": "pong"}

{"action": "page_locked", "data": {"page_id": "page-123"}}
# → Terminal 2 receives: {"event":"page_locked","data":{"page_id":"page-123","locked_by":"test-user-001"}}
```

### Option B: Python Script
```python
import asyncio
import websockets
import json

async def test_collaboration():
    uri = "ws://localhost:8000/ws/courses/COURSE-DEMO-001/collaborate?token=test-user-001"
    async with websockets.connect(uri) as ws:
        # Receive join event
        msg = await ws.recv()
        print("Received:", json.loads(msg))

        # Send ping
        await ws.send(json.dumps({"action": "ping"}))
        pong = await ws.recv()
        print("Pong:", json.loads(pong))

asyncio.run(test_collaboration())
```

---

## 6. SAMPLE DATA

### File Upload
Create a file `sample-course-outline.txt` for Flow 10/11 testing:
```
# Sample Course Outline

## Module 1: Introduction
Welcome to the course. This module covers the basics.

## Module 2: Core Concepts
Deep dive into key concepts with examples.

## Module 3: Assessment
Quiz and final assessment to test understanding.
```

Place it in a location accessible to Postman for the file upload form-data field.

---

## 7. TROUBLESHOOTING

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Set `Authorization: Bearer {{token}}` header |
| 404 Course not found | Create a test course or change `course_id` to an existing value |
| 404 Session not found | Re-run Flow 01 to create a new session (sessions expire) |
| 422 Validation error | Check request body matches the expected Pydantic schema |
| 503 AI disabled | Set `AI_AUTHORING_ENABLED=true` in `.env` and restart |
| WebSocket connection refused | Ensure `uvicorn` is running with `--reload` (not `gunicorn`) |
| Redpanda not connected | `docker ps` — ensure `elearning-redpanda` is running |
| Redis not connected | `docker ps` — ensure `elearning-redis` is running |

---

## 8. FULLY AUTOMATED — Collection Runner

To run all tests without manual intervention:

1. Postman → Collection → **Run Collection**
2. Select the **e2e TEST** folder
3. Check **Keep variable values** (to pass session_id between requests)
4. Click **Run**
5. All 10 e2e requests execute in sequence with automated assertions

Expected runtime: ~30 seconds for full happy path.
