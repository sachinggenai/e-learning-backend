# TPO Gap Analysis — Session Trace Review

> **Role:** Technical Product Owner  
> **Date:** 2026-06-25  
> **Session:** `fd2cc595-a73d-44e8-8904-2328d354b804`  
> **Source:** `session_trace.md`

---

## 1. Expected vs Actual — Ingestion State Machine

### Expected Flow (Design Spec: US-BKND-AI-016/017/019)

```mermaid
stateDiagram-v2
    [*] --> uploaded: POST /ingestions (file upload)
    uploaded --> analyzed: extraction succeeds
    uploaded --> failed: extraction fails
    
    analyzed --> page_plan_ready: POST /propose-breakdown
    page_plan_ready --> plan_approved: POST /review-plan (approved=true)
    page_plan_ready --> analyzed: POST /review-plan (approved=false)
    
    plan_approved --> generated: POST /generate-course
    generated --> completed: POST /generate-course/{id}/apply
    
    completed --> [*]
    failed --> [*]
    
    note right of page_plan_ready: Each section → page<br/>Template type guessed<br/>Plan stored on job
    note right of plan_approved: Plan locked<br/>Ready for LLM generation
    note right of generated: Course + pages<br/>ready in source_metadata<br/>Pending user review
    note right of completed: Pages + components<br/>committed to DB
```

### Actual Flow (Before Fix — from Bug Report)

```mermaid
stateDiagram-v2
    [*] --> uploaded: POST /ingestions
    uploaded --> analyzed: extraction succeeds
    
    analyzed --> analyzed: POST /propose-breakdown ❌ NO STATE TRANSITION
    analyzed --> plan_approved: POST /review-plan (approved=true)
    
    plan_approved --> analyzed: POST /generate-course ❌ REGRESSION!
    analyzed --> completed: POST /generate-course/{id}/apply
    
    completed --> [*]
    
    note right of analyzed: ⚠️ Stuck in 'analyzed'<br/>after propose-breakdown<br/>and after generate-course!
    
    propose-breakdown --> error: ❌ on completed job<br/>"Job must be in 'analyzed' state,<br/>currently 'completed'"
```

### Gap #1: State Machine Regression — ✅ FIXED

| Bug | File | Line | Severity |
|---|---|---|---|
| `propose-breakdown` leaves status at `analyzed` | `ai_ingestion.py` | 199 | **HIGH** — no way to know if plan was generated |
| `start_generation` reverts to `analyzed` | `course_generator.py` | 176 | **CRITICAL** — destroys state, allows re-generation on wrong state |
| No idempotency for completed jobs | `ai_ingestion.py` | 152 | **MEDIUM** — users can't re-read completed job plans |

**Fix applied:** Added `page_plan_ready` and `generated` states. Completed/plan_approved/generated jobs return existing plan idempotently.

---

## 2. Expected vs Actual — Chat + RAG Interaction Loop

### Expected Flow

```mermaid
sequenceDiagram
    participant U as User
    participant R as FastAPI Router
    participant O as ChatOrchestrator
    participant L as DeepSeek LLM
    participant T as ToolExecutor
    participant RAG as RAG Service
    participant DB as PostgreSQL

    U->>R: POST /ai/chat {"prompt":"find cybersecurity courses"}
    R->>O: run_llm_loop()

    rect rgb(240, 248, 255)
        Note over O,DB: Round 1 — LLM decides tools
        O->>O: Load course context
        O->>O: Build system prompt + 7 tool defs
        O->>O: Prune context window
        O->>L: POST deepseek/api (system+msg+tools)
        L-->>O: stop_reason="tool_use"<br/>calls: query_similar_courses
    end

    rect rgb(255, 248, 240)
        Note over O,DB: Tool Execution — RAG
        O->>T: execute("query_similar_courses", {query})
        T->>RAG: query_similar_courses()
        RAG->>DB: Tier-1: pgvector search
        DB-->>RAG: 0 results (pgvector not installed)
        RAG->>DB: Tier-2: full-text search (ts_vector)
        DB-->>RAG: 1 match (score 0.991)
        RAG-->>T: {courses: [...], tier: "tier2"}
        T-->>O: tool_result
    end

    rect rgb(240, 255, 240)
        Note over O,DB: Round 2 — LLM formats response
        O->>L: POST deepseek/api (msg + tool_result)
        L-->>O: stop_reason="end_turn"<br/>content="Found 1 course..."
    end

    O->>O: Close all trace spans
    O-->>R: ChatResponse {content, tool_calls, token_usage}
    R-->>U: HTTP 200
```

### Actual Flow (from session_trace.md)

```mermaid
sequenceDiagram
    participant U as User
    participant R as FastAPI Router
    participant O as ChatOrchestrator
    participant L as DeepSeek LLM
    participant T as ToolExecutor
    participant RAG as RAG Service
    participant DB as PostgreSQL
    participant TR as SessionTracer

    U->>R: POST /ai/chat
    R->>O: run_llm_loop()
    O->>TR: start_span("orchestrator")

    rect rgb(240, 248, 255)
        Note over O,DB: Round 1 — 2,572ms
        O->>O: Load course context (test-chat-001, 0 pages)
        O->>O: Build system prompt + 7 tool defs
        O->>O: Context: 1 message, no pruning needed
        O->>TR: start_span("llm_request", round=1)
        O->>L: POST api.deepseek.com/anthropic/v1/messages<br/>{model:"deepseek-v4-pro[1m]", max_tokens:4096}
        L-->>O: stop_reason="tool_use"<br/>tool: query_similar_courses<br/>tokens: 55 in / 107 out
        O->>TR: end_span(llm_response)
    end

    rect rgb(255, 248, 240)
        Note over O,DB: Tool Execution — 82ms
        O->>TR: start_span("tool_call", query_similar_courses)
        O->>T: execute("query_similar_courses", {query:"cybersecurity awareness"})
        T->>RAG: query_similar_courses()
        RAG->>TR: start_span("rag_retrieval")
        Note over RAG,DB: ⚠️ Tier-1 pgvector: SKIPPED (extension not installed)
        RAG->>DB: Tier-2: to_tsquery('english', 'cybersecur:* & awar:*')
        DB-->>RAG: 1 match: "Cybersecurity Awareness..." (rank 0.991)
        RAG->>TR: end_span(rag_retrieval, tier2, 62ms)
        RAG-->>T: {courses: [1], tier: "tier2"}
        T-->>O: tool_result: success
        O->>TR: end_span(tool_call, success, 82ms)
    end

    rect rgb(240, 255, 240)
        Note over O,DB: Round 2 — 6,943ms
        O->>TR: start_span("llm_request", round=2)
        O->>L: POST api.deepseek.com (msg + tool_result)
        L-->>O: stop_reason="end_turn"<br/>content="Found 1 course..."<br/>tokens: 746 in / 296 out
        O->>TR: end_span(llm_response)
    end

    O->>TR: end_span(orchestrator, total: 9,515ms, 801/403 tok)
    O-->>R: ChatResponse
    R-->>U: HTTP 200
```

---

## 3. Expected vs Actual — RAG Retrieval Tiers

### Expected Architecture

```mermaid
flowchart TD
    Q[("Query: 'cybersecurity awareness'")]
    
    Q --> E[EmbeddingProvider.embed]
    E --> V["OpenAI text-embedding-ada-002<br/>→ 1536-dim semantic vector"]
    
    V --> T1[Tier-1: pgvector Cosine Search]
    T1 --> T1R{"Results?"}
    T1R -->|"≥1 result"| ENRICH[Enrich with excerpts + tone]
    T1R -->|"0 results"| T2
    
    T2[Tier-2: PostgreSQL Full-Text Search]
    T2 --> T2R{"Results?"}
    T2R -->|"≥1 result"| ENRICH
    T2R -->|"0 results"| T3
    
    T3[Tier-3: ILIKE Keyword Search]
    T3 --> ENRICH
    
    ENRICH --> SHAPE["Shape results:<br/>• relevance_score<br/>• template_breakdown<br/>• sample_excerpts (PII redacted)<br/>• tone_notes<br/>• match_summary"]
    
    SHAPE --> OUT[("1 result:<br/>score 0.991<br/>17 pages<br/>4 template types")]
```

### Actual Architecture

```mermaid
flowchart TD
    Q[("Query: 'cybersecurity awareness'")]
    
    Q --> E["EmbeddingProvider.embed<br/>⚠️ MockEmbeddingProvider<br/>SHA-256 → pseudo-vector<br/>(not semantic)"]
    
    E --> T1[Tier-1: pgvector Cosine Search]
    T1 --> T1C{"pgvector<br/>installed?"}
    T1C -->|"❌ NO"| T1SKIP["⚠️ SKIPPED<br/>Returns empty list"]
    
    T1SKIP --> T2[Tier-2: PostgreSQL Full-Text Search]
    T2 --> T2Q["to_tsquery('english',<br/>'cybersecur:* & awar:*')<br/>Matches: courses.title + courses.description"]
    T2 --> T2R{"Results?"}
    T2R -->|"✅ 1 match (rank 0.991)"| ENRICH[Enrich with excerpts + tone]
    T2R -->|"0 results"| T3
    
    T3[Tier-3: ILIKE Keyword Search<br/>⚠️ NOT REACHED]
    
    ENRICH --> SHAPE["Shape results<br/>⚠️ PII redaction active<br/>⚠️ Excerpts from SAFE_FIELDS only"]
    
    SHAPE --> OUT[("✅ 1 result:<br/>score 0.991<br/>17 pages<br/>4 template types")]
    
    style T1SKIP fill:#fff3cd,stroke:#ffc107
    style T3 fill:#e9ecef,stroke:#6c757d
    style E fill:#fff3cd,stroke:#ffc107
```

---

## 4. Expected vs Actual — Session Trace Coverage

### Expected Trace Span Tree

```mermaid
graph TD
    O["orchestrator<br/>interaction_loop<br/>Full chat lifecycle"]
    
    O --> L1["llm_request<br/>chat (round 1)<br/>system_prompt + messages + tools"]
    L1 --> L1R["llm_response<br/>tool_use: query_similar_courses"]
    
    L1R --> TC["tool_call<br/>query_similar_courses<br/>input params"]
    TC --> RAG["rag_retrieval<br/>query_similar_courses<br/>tier details + timing"]
    RAG --> DB1["db_operation<br/>search_vector<br/>SELECT ... <=>"]
    RAG --> DB2["db_operation<br/>search_fulltext<br/>ts_query + ts_rank"]
    RAG --> DB3["db_operation<br/>enrich_results<br/>Page fetch + excerpts"]
    TC --> TCR["tool_result<br/>output: 1 course found"]
    
    TCR --> L2["llm_request<br/>chat (round 2)<br/>messages + tool_result"]
    L2 --> L2R["llm_response<br/>end_turn: formatted answer"]
    
    O --> PRUNE["context_prune<br/>token count + strategy"]
    O --> OEND["orchestrator_end<br/>total tokens + latency"]
    
    style DB1 fill:#e9ecef,stroke:#6c757d,stroke-dasharray: 5 5
    style DB2 fill:#e9ecef,stroke:#6c757d,stroke-dasharray: 5 5
    style DB3 fill:#e9ecef,stroke:#6c757d,stroke-dasharray: 5 5
    style PRUNE fill:#e9ecef,stroke:#6c757d,stroke-dasharray: 5 5
```

### Actual Trace Span Tree (from PostgreSQL)

```mermaid
graph TD
    O["✅ orchestrator<br/>interaction_loop<br/>1,745ms | 57/23 tok"]
    
    O --> L1["✅ llm_request<br/>chat (round 1)<br/>1,745ms | 57/23 tok<br/>content: 'Paris'"]
    L1 --> L1R["✅ end_turn (no tools)"]
    
    O2["✅ orchestrator<br/>interaction_loop<br/>9,515ms | 801/403 tok"]
    
    O2 --> L2["✅ llm_request<br/>chat (round 1)<br/>2,572ms | 55/107 tok<br/>stop: tool_use"]
    L2 --> TC["✅ tool_call<br/>query_similar_courses<br/>82ms | success"]
    TC --> RAG["✅ rag_retrieval<br/>query_similar_courses<br/>62ms | tier2"]
    
    RAG -.-> DB1["❌ db_operation<br/>search_fulltext<br/>NOT TRACED"]
    RAG -.-> DB2["❌ db_operation<br/>enrich_results<br/>NOT TRACED"]
    
    TC --> L3["✅ llm_request<br/>chat (round 2)<br/>6,943ms | 746/296 tok<br/>content: 'Found 1 course...'"]
    
    O2 -.-> PRUNE["❌ context_prune<br/>NOT TRACED"]
    
    style DB1 fill:#f8d7da,stroke:#dc3545,stroke-dasharray: 5 5
    style DB2 fill:#f8d7da,stroke:#dc3545,stroke-dasharray: 5 5
    style PRUNE fill:#f8d7da,stroke:#dc3545,stroke-dasharray: 5 5
```

---

## 5. Gap Summary

### 🔴 Critical Gaps (Fixed in This Session)

| ID | Gap | Before | After | Impact |
|---|---|---|---|---|
| **G-01** | Ingestion state machine regression | `start_generation` reverted to `analyzed` | Set to `generated` | Could not distinguish "just analyzed" from "course generated" |
| **G-02** | Missing `page_plan_ready` state | `propose-breakdown` left status at `analyzed` | New `page_plan_ready` state added | No way to know if plan exists without checking `extracted_sections` |
| **G-03** | `propose-breakdown` rejected completed jobs | HTTP 400 `INVALID_STATE` | Returns existing plan idempotently | Users blocked from re-reading plans on completed pipelines |
| **G-04** | RAG end_span crash | `TypeError: unexpected keyword argument 'metadata'` | Added `metadata` param to `end_span()` | Every RAG call threw 503, tool always errored |

### 🟡 Medium Gaps (Require Follow-up)

| ID | Gap | Current State | Target State | Effort |
|---|---|---|---|---|
| **G-05** | No pgvector extension | Tier-1 vector search always skipped | Install pgvector + pgvector Python package | 30 min |
| **G-06** | Mock embedding provider | SHA-256 pseudo-vectors (not semantic) | OpenAI `text-embedding-ada-002` for real embeddings | Config change + API key |
| **G-07** | Course generation uses mock | `provenance.model: "mock"` | Use DeepSeek for content generation | Wire `course_generator` to `LLMClient` |
| **G-08** | DB operations not traced | Only 0 `db_operation` spans in trace | Trace SQL queries with params per operation | Add tracer to repositories |
| **G-09** | Context pruning not traced | No `context_prune` spans | Trace messages removed, token delta, strategy used | Add tracer to `ContextManager.prune()` |

### 🟢 Low Gaps (Nice to Have)

| ID | Gap | Current State | Target State | Effort |
|---|---|---|---|---|
| **G-10** | Only 1 similar course in org | RAG finds at most 1 match | Seed 5-10 diverse courses for richer RAG results | 1 hour |
| **G-11** | Streaming spans missing | No per-chunk trace for SSE | Per-chunk latency and token accumulation | Add tracer to `_anthropic_stream` |
| **G-12** | Cost tracking not in trace | `cost_tracker` runs separately | Merge cost data into trace aggregates | Wire `CostTracker` → `SessionTracer` |
| **G-13** | No `model_tier_router` trace | Planner vs Generator decision invisible | Trace routing decision with reason | Add span in `ModelTierRouter.classify_task()` |

---

## 6. Overall Health Dashboard

```mermaid
pie title Session Trace Health (7 spans analyzed)
    "LLM Calls (DeepSeek)" : 3
    "Tool Calls" : 1
    "RAG Retrievals" : 1
    "Orchestrator" : 2
```

```mermaid
pie title Trace Coverage (Expected vs Actual)
    "Traced (7 spans)" : 7
    "Missing DB ops" : 3
    "Missing context prune" : 1
    "Missing streaming chunks" : 14
```

| Metric | Value | Status |
|---|---|---|
| LLM calls traced | 3/3 (100%) | ✅ |
| Tool calls traced | 1/1 (100%) | ✅ |
| RAG retrievals traced | 1/1 (100%) | ✅ |
| DB operations traced | 0/3 (0%) | ❌ |
| Context pruning traced | 0/1 (0%) | ❌ |
| Streaming chunks traced | 0/14 (0%) | ❌ |
| **Overall trace coverage** | **7/22 (32%)** | 🟡 |
| LLM provider | DeepSeek (real) | ✅ |
| RAG tier | Tier-2 (fallback) | 🟡 |
| Embedding quality | Mock (pseudo-vector) | 🔴 |
| Content generation | Mock (boilerplate) | 🔴 |
| State machine correctness | 6 states, no regressions | ✅ |

---

## 7. Recommended Action Plan

| Priority | Action | Story |
|---|---|---|
| **P0 — Done** | Fix state machine regression + idempotency | ✅ This session |
| **P0 — Done** | Fix RAG tracer crash | ✅ This session |
| **P1** | Install pgvector extension → enable Tier-1 semantic search | US-BKND-AI-015-T1 |
| **P1** | Switch to OpenAI embeddings → real semantic vectors | US-BKND-AI-015-EMBED |
| **P1** | Add DB operation tracing → full SQL observability | US-BKND-AI-TRACE-02 |
| **P2** | Wire course generation to DeepSeek → AI-generated content | US-BKND-AI-019-LLM |
| **P2** | Add context pruning tracing | US-BKND-AI-TRACE-03 |
| **P2** | Seed 5-10 similar courses for richer RAG | US-BKND-AI-015-SEED |
| **P3** | Per-chunk streaming trace | US-BKND-AI-TRACE-04 |
| **P3** | Cost tracking in trace aggregates | US-BKND-AI-TRACE-05 |
