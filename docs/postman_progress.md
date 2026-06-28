# Postman Collection Validation — Progress Report

> **Date:** 2026-06-28
> **Branch:** `AI-Architecture-update`
> **Collection:** `E-Learning_AI_Postman_Collection.json` (82 requests, 20 folders)
> **Environment:** Windows 11, Docker Desktop, Python 3.11, FastAPI :8000

---

## 1. Test Environment Configuration

### Stack Running
| Service | Port | Status |
|---------|------|--------|
| PostgreSQL 16 + pgvector | 5432 | ✅ Healthy |
| Redis 7 | 6379 | ✅ Healthy |
| Redpanda (Kafka) | 19092 | ✅ Healthy |
| MinIO (S3) | 9000/9001 | ✅ Healthy |
| FastAPI Backend | 8000 | ✅ AI Enabled |
| content-writer-mcp | 8001 | ✅ |
| safety-scan-mcp | 8002 | ✅ |
| template-registry-mcp | 8003 | ✅ |

### Key .env Settings
```ini
AI_AUTHORING_ENABLED=true
AI_GENERATION_PROVIDER=anthropic
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
AI_PRIMARY_MODEL=deepseek-v4-pro[1m]
AUTH_MOCK_MODE=enabled
FEATURE_DURABLE_WORKFLOW_ENGINE=true
FEATURE_SIMILAR_COURSE_RETRIEVAL=true
```

### Test Data
- `COURSE-DEMO-001` — seeded in DB
- `token=test-user-001` — mock auth user

---

## 2. Test Run History

### Run 1 — Baseline (AI disabled, no auth, no course)
| Metric | Value |
|--------|-------|
| Passed | 2 |
| Failed | 80 |
| Root Cause | `AI_AUTHORING_ENABLED=false` — all AI routes returned 404 |

### Run 2 — AI Enabled (no auth, no course)
| Metric | Value |
|--------|-------|
| Passed | 2 |
| Failed | 80 |
| Root Cause | AI routes mounted but auth failed (401) + course not in DB |

### Run 3 — AI + Mock Auth + Course Seeded (P0 fixes)
| Metric | Value |
|--------|-------|
| Passed | ~20 |
| Failed | ~62 |
| Improvements | Session creation 201 ✅, real LLM responding ✅, RAG working ✅ |
| Remaining issues | Session deleted before dependent flows, proposal_id not captured |

### Run 4 — After Postman Collection Fixes (40 fixes applied)
| Metric | Value |
|--------|-------|
| Passed | 65+ |
| Failed | 17 |
| Fixes applied | Test script field names, Authorization headers, URL templates, body fields, session delete removal |

---

## 3. Postman Collection Fixes Applied (Run 4)

### Fix 1: Test Script Field Names (7 types)
Postman test scripts referenced JSON fields in **snake_case** but API responses use **camelCase** + nesting.

| Collection Expected (old) | API Returns (actual) | Fix Applied |
|---|---|---|
| `json.session_id` | `json.session.sessionId` | ✅ |
| `json.ai_authoring_enabled` | `json.aiAuthoringEnabled` | ✅ |
| `json.proposal_id` | `json.proposal.proposal_id` | ✅ |
| `json.course_id` | `json.courseId` | ✅ |
| `json.page_id` | `json.pageId` | ✅ |
| `json.job_id` | `json.jobId` | ✅ |
| `json.total_pages` | `json.totalPages` | ✅ |

### Fix 2: Authorization Headers
Added `Authorization: Bearer {{token}}` to all AI endpoint requests that were missing it. (40+ requests)

### Fix 3: URL Templates
- `POST /api/v1/ai/proposals//apply` → `POST /api/v1/ai/proposals/{{proposal_id}}/apply`
- `POST /api/v1/ai/proposals//cancel` → `POST /api/v1/ai/proposals/{{proposal_id}}/cancel`

### Fix 4: Request Body Fields
Reverted incorrect camelCase request bodies back to snake_case (API expects snake_case for input).

### Fix 5: Session Lifecycle
Removed "03-Delete Session (Cleanup)" from FLOW 01 — it was deleting the session before dependent flows could use it.

---

## 4. Remaining 17 Failures — RCA

### Category A: Needs seeded page data (4 failures)
| Flow | Test | Error | Fix |
|------|------|-------|-----|
| FLOW 03 | 02-Fetch Page | 422 — missing page_id | Seed a page in COURSE-DEMO-001 |
| FLOW 08 | 01-Propose Delete Page | 422 — needs page_id | Seed a page |
| FLOW 08 | 02-Confirm Delete | 422 — needs proposal_id + token | Cascade from above |
| FLOW 08 | (TypeError in test) | `Cannot read properties of undefined` | Cascade failure |

### Category B: Apply/Cancel returning 403 instead of 200 (2 failures)
| Flow | Test | Error | Root Cause |
|------|------|-------|------------|
| FLOW 05/06 | 03-Apply Proposal | 403 | Proposal requires valid `confirmation_token` for destructive ops |
| FLOW 07 | 02-Apply Update Proposal | 403 | Same — confirmation token system (US-BKND-AI-049) |

**RCA:** These endpoints require a confirmation token (`confirmationToken`) generated via `POST /api/v1/ai/proposals/{id}/confirm`. The collection applies proposals directly without generating a confirmation token first.

### Category C: Needs ingestion file upload (4 failures)
| Flow | Test | Error | Root Cause |
|------|------|-------|------------|
| FLOW 10/11 | 01-Upload File | 422 | No file attached (multipart) |
| FLOW 10/11 | 03-Propose Breakdown | 404 | No ingestion job exists yet |
| FLOW 10/11 | 04-Review Plan | 404 | Cascade |
| FLOW 10/11 | 06-Poll Status | 405 | Wrong HTTP method for status check |

### Category D: Needs course content (2 failures)
| Flow | Test | Error | Root Cause |
|------|------|-------|------------|
| FLOW 10/11 | 05-Generate Course | 422 | Course has 0 pages — nothing to generate |
| FLOW 12/13/14 | 01-Export SCORM | 422 | No course content to export |

### Category E: Export validation (1 failure)
| Flow | Test | Error | Root Cause |
|------|------|-------|------------|
| FLOW 09 | 02-Validate Export Readiness | 422 | Course has no pages/scoring/navigation |

### Category F: Workflow engine endpoints not found (3 failures)
| Flow | Test | Error | Root Cause |
|------|------|-------|------------|
| WORKFLOW | 01-Submit Workflow | 404 | URL mismatch — `/api/v1/workflows/submit` expected, actual `/api/v1/ai/workflows` |
| WORKFLOW | 02-Poll Status | 404 | Same URL mismatch |
| WORKFLOW | 03-Get Events | 404 | Same URL mismatch |

### Category G: WebSocket (1 error)
| Test | Error | Root Cause |
|------|-------|------------|
| WebSocket Collaboration | Invalid protocol: ws: | Newman doesn't support WebSocket connections |

---

## 5. Verified Working — Key Wins

### AI Core Functionality
| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /api/v1/health` | ✅ 200 | Always works |
| `GET /api/v1/ai/feature-status` | ✅ 200 | AI enabled, DeepSeek v4-pro confirmed |
| `POST /api/v1/ai/sessions` | ✅ 201 | Session creation with mock auth |
| `GET /api/v1/ai/sessions/{id}` | ✅ 200 | Session retrieval |
| `DELETE /api/v1/ai/sessions/{id}` | ✅ 200 | Session deletion |

### AI Tools (with valid session)
| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/ai/tools/list_pages` | ✅ 200 | Returns empty page list |
| `POST /api/v1/ai/tools/query_similar_courses` | ✅ 200 | RAG retrieval working — tier3 |
| `POST /api/v1/ai/tools/validate_course` | ✅ 200 | Course validation active |

### AI Chat — Real LLM
| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/ai/chat` | ✅ 200 | **DeepSeek v4-pro responding** with context analysis |
| `GET /api/v1/ai/chat/history` | ✅ 200 | Chat history retrieval |

**Verified LLM Response:**
```
Model: deepseek-v4-pro[1m]
Token usage: 1775 input / 589 output
Latency: 11.2s
Response: Context-aware greeting mentioning course name, page count,
          and available template types (text-content, tabs, accordion,
          click-reveal, final-assessment)
RAG: Similar course retrieval active (tier3) — found COURSE-DEMO-001
```

### AI Proposals
| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/ai/proposals` | ✅ 201 | Proposal creation with `create_page` operation |
| `GET /api/v1/ai/proposals/` | ✅ 200 | Empty list (no proposals in DB initially) |
| `GET /api/v1/ai/proposals/{id}` | ✅ 200 | Single proposal retrieval |
| `GET /api/v1/ai/proposals?session_id={id}` | ✅ 200 | Filtered list |

### Templates & Components
| Endpoint | Status |
|----------|--------|
| `GET /api/v1/ai/templates` | ✅ 200 |
| `GET /api/v1/ai/templates/{type_key}` | ✅ 200 |
| `GET /api/v1/component-types` | ✅ 200 |
| `GET /api/v1/component-types/{type}` | ✅ 200 |

### MCP Protocol Adapters
| Endpoint | Status |
|----------|--------|
| `GET :8001/health` (content-writer) | ✅ 200 |
| `GET :8002/health` (safety-scan) | ✅ 200 |
| `GET :8003/health` (template-registry) | ✅ 200 |

---

## 6. Progress Summary

```
Run 1 (baseline):        ██░░░░░░░░░░░░░░░░░░  2/82  (02%)
Run 2 (AI enabled):      ██░░░░░░░░░░░░░░░░░░  2/82  (02%)  [all 404 → AI disabled]
Run 3 (P0 fixes):        ██████░░░░░░░░░░░░░░ 20/82  (24%)  [session + LLM working!]
Run 4 (collection fix):  █████████████████░░░ 65/82  (79%)  [proposals + tools]
```

**65 of 82 tests now pass.** The 17 remaining failures fall into 3 actionable categories:

1. **Need confirmation token flow** (2 tests) — Add `POST /proposals/{id}/confirm` step before apply/cancel
2. **Need seeded pages** (6 tests) — Add page creation to test setup
3. **Need file upload** (4 tests) — Add test file to collection
4. **Workflow URL mismatch** (3 tests) — Fix URL to match actual API routes
5. **WebSocket** (1 test) — Newman limitation, test manually
6. **Export validation** (1 test) — Course needs content

---

## 7. Root Cause Summary Table

| # | Category | Failures | Root Cause | Fix Complexity |
|---|----------|----------|------------|----------------|
| 1 | Confirmation token | 2 | Apply/Cancel need `confirmationToken` from `/confirm` endpoint | Add step to collection |
| 2 | Page data | 6 | No pages seeded in test course | Add page creation to setup |
| 3 | File upload | 4 | No file attached, no ingestion job | Add test file + multipart form |
| 4 | Workflow URLs | 3 | Collection uses wrong URL paths | Fix URL templates |
| 5 | WebSocket | 1 | Newman can't do WS | Manual test |
| 6 | Export | 1 | Course has 0 pages | Cascade from page seeding |

---

## 8. Files Modified

| File | Changes |
|------|---------|
| `.env` | `AI_AUTHORING_ENABLED=true`, `AI_GENERATION_PROVIDER=anthropic`, `AUTH_MOCK_MODE=enabled`, DeepSeek API keys uncommented, feature flags enabled |
| `E-Learning_AI_Postman_Collection.json` | 40+ fixes: test script field names, auth headers, URL templates, body fields, session lifecycle |
| `TPO-Gap-Analysis-TRD.md` | Part D appended — live validation RCA with full failure categorization |
| `docker-compose.yml` | `${VAR}` env substitution, Redpanda healthcheck, removed deprecated `version` |
| `app/services/ai/template_contracts.py` | `db` made optional (`AsyncSession | None = None`) |

---

*Report generated 2026-06-28 from 4 live Newman runs against full AI stack.*
