# Session Trace — Full Flow Validation Report

> **Date:** 2026-06-25 | **Branch:** `demo-course-AI-pradeep`  
> **LLM:** `deepseek-v4-pro[1m]` via `https://api.deepseek.com/anthropic`  
> **Session:** `fd2cc595-a73d-44e8-8904-2328d354b804`

---

## 1. propose-breakdown on Completed Job — ✅ FIXED

**The exact curl that previously returned `INVALID_STATE` now returns the plan idempotently.**

| | Before Fix | After Fix |
|---|---|---|
| `POST .../e33a4ed2.../propose-breakdown` | `{"status":"error","code":"INVALID_STATE","message":"Job must be in 'analyzed' state, currently 'completed'."}` | `{"status":"ok","idempotent":true,"total_proposed":17,"message":"Returning existing plan (job already processed)."}` |

**Root cause:** The `propose-breakdown` endpoint required `job.status == "analyzed"` but the job had gone through the full pipeline (analyzed → page_plan_ready → plan_approved → generated → completed). The state machine had 3 bugs:

1. `start_generation()` set status back to `"analyzed"` (regression) → fixed to `"generated"`
2. `propose-breakdown` left status as `"analyzed"` (no transition) → fixed to `"page_plan_ready"`  
3. No idempotency for completed jobs → now returns existing plan for `completed`/`plan_approved`/`generated` states

**Fixed state machine:**
```
upload → analyzed → page_plan_ready → plan_approved → generated → completed
                                                                    │
                                            propose-breakdown ──────┘
                                            → idempotent: returns existing plan
```

---

## 2. Ingestion Job — Complete

```
Job:      e33a4ed2-65df-46c1-8fed-d31d8cf6b597
Status:   completed
File:     SB2-Cybersecurity Awareness for the Modern Workplace.docx
Type:     docx (328,641 bytes)
Course:   Cybersecurity Awareness for the Modern Workplace
Sections: 17 extracted
Pages:    17 generated + applied
Model:    mock (content generation)
```

---

## 3. LLM Calls — DeepSeek Verified

### Test 3a: Simple Chat
```
Prompt:    "Reply with exactly one word: the capital of France"
Response:  "Paris"
Mock mode: FALSE — real DeepSeek API call
Tokens:    57 input / 23 output
Latency:   2,094ms
```
→ DeepSeek `deepseek-v4-pro[1m]` answered correctly without tool calls.

### Test 3b: RAG Chat
```
Prompt:    "find courses about cybersecurity awareness and list them"
Response:  "Here's what I found — there's 1 course related to cybersecurity..."
Mock mode: FALSE — real DeepSeek API call
Tokens:    801 input / 403 output
Latency:   10,234ms (multi-round)
```
→ DeepSeek auto-selected `query_similar_courses` tool, executed RAG, formatted results.

### What DeepSeek receives per call:

**System Prompt:**
```
You are an AI course authoring assistant. You help instructors create and edit e-learning courses.

CURRENT COURSE: "test-chat-001"
Status: draft
Pages: 0 total

Available template types: text-content, tabs, accordion, click-reveal, final-assessment

IMPORTANT RULES:
1. NEVER mutate data directly — always create proposals first
2. Always validate before proposing — use the validate tool
3. Always fetch current state — never trust conversation history
4. For destructive actions — always require explicit user confirmation
5. Stay within the session's course scope — do not access other courses
6. The `query_similar_courses` tool returns example courses for tone and
   structural reference ONLY. Do NOT derive API contracts, validation
   rules, template schemas, or configuration values from these results.
7. If `query_similar_courses` returns empty results, continue generation
   without examples.
8. Reference pages by their title or position, not by internal IDs
```

**7 Tool Definitions:** `list_pages`, `fetch_page`, `query_similar_courses`, `propose_create_page`, `propose_update_page`, `propose_delete_page`, `validate_course`

**API Endpoint:** `POST https://api.deepseek.com/anthropic/v1/messages`

---

## 4. RAG — Similar Course Retrieval

```
Tool called:  query_similar_courses
Input:        {"query": "cybersecurity awareness"}
Tier used:    tier2 (PostgreSQL full-text search)
Results:      1 match found
  - Title:    "Cybersecurity Awareness for the Modern Workplace"
  - Score:    0.991
  - Pages:    17
  - Type:     text-content, tabs, accordion, final-assessment
```

**RAG Internals (no LLM involved):**
```
Tier-1 (pgvector):  skipped (pgvector extension not installed)
Tier-2 (ts_vector): query → to_tsquery('english', 'cybersecur:* & awar:*')
                    → matched courses.title + courses.description
                    → rank: 0.991
Tier-3 (ILIKE):     not reached (tier-2 succeeded)
```

---

## 5. Session Trace — Full Call Tree

### 5.1 Aggregate Statistics

```
Total spans:    7
LLM calls:      3 (2 chat rounds)
RAG retrievals: 1 (tier-2 full-text)
Tool calls:     1 (query_similar_courses)
DB operations:  0 (RAG reads, not traced as DB ops)
Errors:         0
Total tokens:   1,716 input / 852 output
Total latency:  22,663ms
Models used:    [deepseek-v4-pro[1m]]
```

### 5.2 Span Details

| # | Type | Operation | Status | Latency | Tokens | Detail |
|---|---|---|---|---|---|---|
| 1 | orchestrator | interaction_loop | success | 1,745ms | 57/23 | → "Paris" |
| 2 | llm_request | chat | success | 1,745ms | 57/23 | → "Paris" |
| 3 | orchestrator | interaction_loop | success | 9,515ms | 801/403 | (RAG round) |
| 4 | llm_request | chat (round 1) | success | 2,572ms | 55/107 | → tools: [query_similar_courses] |
| 5 | tool_call | query_similar_courses | success | 82ms | — | → RAG execution |
| 6 | rag_retrieval | query_similar_courses | success | 62ms | — | → 1 result (tier2) |
| 7 | llm_request | chat (round 2) | success | 6,943ms | 746/296 | → formatted answer |

### 5.3 LLM Prompt (sent to DeepSeek — Round 1 of RAG chat)

```json
{
  "model": "deepseek-v4-pro[1m]",
  "max_tokens": 4096,
  "temperature": 0.7,
  "system": "You are an AI course authoring assistant...",
  "messages": [
    {"role": "user", "content": "find courses about cybersecurity awareness and list them"}
  ],
  "tools": [
    {"name": "list_pages", ...},
    {"name": "fetch_page", ...},
    {"name": "query_similar_courses",
     "description": "Search for similar courses within your organization to use as examples...",
     "input_schema": {
       "type": "object",
       "properties": {
         "session_id": {"type": "string"},
         "query": {"type": "string"},
         "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20}
       },
       "required": ["session_id", "query"]
     }
    },
    {"name": "propose_create_page", ...},
    {"name": "propose_update_page", ...},
    {"name": "propose_delete_page", ...},
    {"name": "validate_course", ...}
  ]
}
```

### 5.4 LLM Response (DeepSeek — Round 1)

```json
{
  "stop_reason": "tool_use",
  "content": [
    {
      "type": "tool_use",
      "id": "call_00_...",
      "name": "query_similar_courses",
      "input": {"query": "cybersecurity awareness"}
    }
  ],
  "usage": {"input_tokens": 55, "output_tokens": 107}
}
```

### 5.5 Tool Execution (internal — no LLM)

Input → `query_similar_courses(session_id, query="cybersecurity awareness", max_results=5)`  
Output → `{"courses": [{...}], "total_count": 1, "retrieval_tier_used": "tier2"}`

### 5.6 LLM Response (DeepSeek — Round 2, final)

```json
{
  "stop_reason": "end_turn",
  "content": [{"type": "text", "text": "Here's what I found — there's **1 course** related to cybersecurity awareness:\n\n### Cybersecurity Awareness for the Modern Workplace\n| Detail | Value |\n|---|---|\n| **Relevance** | 0.991 |\n| **Pages** | 17 |\n| **Templates** | text-content, tabs, accordion, final-assessment |"}],
  "usage": {"input_tokens": 746, "output_tokens": 296}
}
```

---

## 6. DB Persistence — PostgreSQL

All 7 spans persisted to `ai_session_trace_spans` table:

```
              span_id               |  trace_type   |       operation       | status  |  ms  | tok_in | tok_out
-------------------------------------+---------------+-----------------------+---------+------+--------+--------
0711dd00-... | orchestrator  | interaction_loop      | success | 1745 | 57     | 23
c0bff81c-... | llm_request   | chat                  | success | 1745 | 57     | 23
e80704bd-... | llm_request   | chat                  | success | 2572 | 55     | 107
cd7d1988-... | orchestrator  | interaction_loop      | success | 9515 | 801    | 403
6f4c075d-... | rag_retrieval | query_similar_courses | success | 62   |        |
4a3876f7-... | tool_call     | query_similar_courses | success | 82   |        |
8f57ddf8-... | llm_request   | chat                  | success | 6943 | 746    | 296
```

---

## 7. API Endpoints

```bash
# Ingestion job status
GET /api/v1/ai/ingestions/{job_id}

# Page breakdown (idempotent for completed jobs)
POST /api/v1/ai/ingestions/{job_id}/propose-breakdown

# AI Chat (non-streaming)
POST /api/v1/ai/chat

# AI Chat (SSE streaming)
POST /api/v1/ai/chat/stream

# Session trace (full I/O)
GET /api/v1/ai/sessions/{session_id}/trace

# Session trace (summary only)
GET /api/v1/ai/sessions/{session_id}/trace/summary

# Clear session traces
DELETE /api/v1/ai/sessions/{session_id}/trace
```

---

## 8. Configuration

| Variable | Value |
|---|---|
| `ANTHROPIC_BASE_URL` | `https://api.deepseek.com/anthropic` |
| `AI_PRIMARY_MODEL` | `deepseek-v4-pro[1m]` |
| `AI_FALLBACK_MODEL` | `deepseek-v4-flash` |
| `AI_AUTHORING_ENABLED` | `true` |
| `FEATURE_SIMILAR_COURSE_RETRIEVAL` | `true` |
| `EMBEDDING_PROVIDER` | `mock` (deterministic SHA-256) |
| `ENABLE_PGVECTOR` | `false` (full-text fallback used) |

---

## 9. Verdict

| Test | Status |
|---|---|
| propose-breakdown on completed job | ✅ Idempotent — returns plan |
| Ingestion GET | ✅ 17-section DOCX ingested |
| DeepSeek LLM chat | ✅ Real API calls, no mock |
| LLM tool selection (RAG) | ✅ Auto-selects query_similar_courses |
| RAG retrieval | ✅ Tier-2 full-text, 0.991 score match |
| Session trace | ✅ 7 spans with full I/O payloads |
| DB persistence | ✅ All spans in PostgreSQL |
| State machine | ✅ analyzed → page_plan_ready → plan_approved → generated → completed |
