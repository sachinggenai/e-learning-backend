# AI Migration Prompt: E-Learning Backend — Single-Agent to Pragmatic Multi-Agent Architecture

> **Generated:** 2026-06-27
> **Based on:** 60+ files analyzed across codebase, 12 Mermaid flowcharts, TPO Gap Analysis TRD (13 gaps), Agentic AI Architecture Gap Analysis (21 gaps)
> **Target Branch:** `demo-course-AI-pradeep-01`
> **Repository:** `C:\Users\ADMIN\e-learning-backend`

---

## PROMPT START — Copy everything below this line

---p

You are an Agentic AI Architect and Senior Full-Stack Python Engineer. Your task is to migrate an e-learning backend from a **single-agent tool-using architecture** to a **pragmatic multi-agent architecture** with LangGraph orchestration, 3 specialist LLM agents, 3 MCP servers, parallel content generation via Redis Streams, and OpenTelemetry observability.

**CRITICAL RULE:** Build only what creates real user value. Do NOT build all 9 agents, all 9 MCP servers, or Kubernetes. The target is a **pragmatic evolution** capturing 80% of the multi-agent benefit at ~35% of the complexity. See the "What NOT to Build" section below.


---

## PART 1: CURRENT STATE (What Exists Today)

### 1.1 Repository Structure

```
C:\Users\ADMIN\e-learning-backend\
├── app/
│   ├── main.py                          # FastAPI app, lifespan, middleware registration
│   ├── services/
│   │   ├── ai/                          # 43 Python files — AI service layer
│   │   │   ├── chat_orchestrator.py     # Single-agent LLM interaction loop (CORE)
│   │   │   ├── llm_client.py            # Anthropic SDK + Mock provider with SSE streaming
│   │   │   ├── config.py                # Singleton AIConfig, 4-model registry (DeepSeek + Claude)
│   │   │   ├── safety_service.py        # 3-layer guards: 9 injection patterns + 10 PII patterns + output blocking
│   │   │   ├── json_repair.py           # 12-strategy deterministic JSON repair pipeline
│   │   │   ├── course_generator.py      # Sequential mock/LLM course generation
│   │   │   ├── course_assembler.py      # Proposal-to-DB transformation (atomic, audited)
│   │   │   ├── proposal_service.py      # Propose-validate-confirm-apply lifecycle
│   │   │   ├── ingestion_service.py     # File upload + validation + SHA-256 dedup
│   │   │   ├── document_extractor.py    # PDF (pdfplumber) + DOCX (python-docx)
│   │   │   ├── similar_course_service.py # 3-tier RAG: pgvector → fulltext → keyword
│   │   │   ├── context_manager.py       # Token counting + 3 pruning strategies
│   │   │   ├── model_tier_router.py     # Planner vs Generator 2-tier task routing
│   │   │   ├── tool_executor.py         # Stateless tool dispatch (hardcoded dictionary)
│   │   │   ├── session_tracer.py        # Custom span-based I/O capture with DB persistence
│   │   │   ├── cost_tracker.py          # Token counting + pricing + budget enforcement
│   │   │   ├── embedding_provider.py    # OpenAI + Mock embedding backends
│   │   │   ├── dependency_analyzer.py   # Branching/scoring/navigation impact analysis
│   │   │   ├── policy_engine.py         # Rule-based auto-apply decisions
│   │   │   ├── lock_manager.py          # In-memory READ/WRITE/SESSION locks
│   │   │   ├── stale_detector.py        # 3-way merge + conflict reporting
│   │   │   ├── dead_letter_queue.py     # In-memory DLQ with exponential backoff
│   │   │   ├── confirmation_token_service.py # HMAC-SHA256 scope-bound tokens
│   │   │   ├── idempotency_service.py   # Exactly-once apply semantics
│   │   │   ├── outbox_service.py        # Transactional outbox pattern
│   │   │   ├── audit_service.py         # Append-only audit log
│   │   │   ├── audit_query_service.py   # Filtered audit log queries
│   │   │   ├── diff_engine.py           # Before/after structural diff
│   │   │   ├── validation_engine.py     # JSON Schema + business rules validation
│   │   │   ├── template_contracts.py    # Template schema definitions
│   │   │   ├── feedback_collector.py    # RLHF feedback collection
│   │   │   ├── prompt_registry.py       # Versioned prompts with A/B testing
│   │   │   ├── template_harvester.py    # TF-IDF novelty detection
│   │   │   ├── pattern_clusterer.py     # DBSCAN clustering
│   │   │   └── job_status_service.py    # Async job tracking + course ops
│   │   └── workflow/                    # Durable workflow engine (separate package)
│   │       ├── orchestrator.py          # PostgreSQL-backed poll loop, SELECT FOR UPDATE SKIP LOCKED
│   │       ├── step_registry.py         # Decorator-based singleton step registry
│   │       ├── types.py                 # WorkflowStatus enum, StepResult dataclass
│   │       └── steps/
│   │           ├── course_generation.py # 4 states: validate_input→generate_pages→validate_course→create_batch_proposal
│   │           └── scorm_export.py      # 5 states: validate_course→generate_manifest→package_assets→create_zip→complete
│   ├── routers/
│   │   ├── ai_chat.py                   # POST /chat, POST /chat/stream (SSE), GET /chat/history
│   │   ├── ai_proposals.py              # CRUD + delete-page + confirm-delete
│   │   ├── ai_confirmations.py          # POST /proposals/{id}/confirm
│   │   ├── ai_admin.py                  # Safety events, audit logs, audit summary
│   │   ├── ai_ingestion.py              # Upload + generate-course + review-plan
│   │   ├── ai_sessions.py               # Session CRUD
│   │   ├── ai_config.py                 # Feature-status endpoint
│   │   ├── ai_templates.py              # Template contract listing
│   │   ├── ai_tools.py                  # 11 tool endpoints (list_pages, fetch_page, etc.)
│   │   ├── ai_similar_courses.py        # Similar course search
│   │   ├── ai_tracing.py                # Session trace/debug endpoints
│   │   ├── workflows.py                 # 6 endpoints (submit, status, cancel, retry, events, list)
│   │   └── ws_collaboration.py          # WebSocket collaboration (Redis pub/sub)
│   ├── models/
│   │   ├── ai_models.py                 # 8 ORM models (sessions, proposals, tokens, audit, outbox, chat, idempotency, ingestion)
│   │   ├── workflow.py                  # 3 ORM models (type_definitions, jobs, job_events)
│   │   ├── ai_admin_override.py         # Admin bypass audit trail
│   │   ├── ai_safety_event.py           # Immutable safety events
│   │   └── course_embedding.py          # pgvector Vector(1536) + JSONB fallback
│   ├── middleware/
│   │   ├── ai_telemetry.py              # Custom X-Trace-ID propagation + timing (NOT OpenTelemetry)
│   │   └── ai_rate_limiter.py           # 3-tier sliding window, IN-PROCESS store (TODO: Redis)
│   └── repositories/
│       └── similar_course_repo.py       # pgvector/fulltext/keyword search + enrichment
├── tests/
│   └── run_*.py                         # 20 standalone test runners, 834 tests, ALL PASSING
├── docker-compose.yml                   # PostgreSQL 16 + pgvector, Redis 7, Redpanda (Kafka), MinIO
├── Dockerfile.production                # Python 3.12-slim, gunicorn + uvicorn
├── render.yaml                          # Render.com deployment
├── requirements.txt                     # fastapi, anthropic, pgvector, aiokafka, redis, pdfplumber, python-docx, etc.
└── .env.example                         # All AI env vars with defaults
```

### 1.2 Current Architecture: Single-Agent Tool-Using System

**The Orchestrator Loop** (`app/services/ai/chat_orchestrator.py`, method `run_llm_loop()`):

```
1. SAFETY CHECK: SafetyService.scan_input() — 9 injection patterns + 10 PII patterns
2. CONTEXT PRUNING: ContextManager.prune() — sliding_window/priority/summarize
3. LLM CALL: LLMClient.chat() — Anthropic SDK (DeepSeek or Claude) or Mock provider
4. RESPONSE PARSING: Extract content + tool_calls from LLM response
5. TOOL EXECUTION: ToolExecutor.execute() — stateless dispatch to 11 tools
6. LOOP: If tool_calls, append results to conversation, goto step 3 (max 4 rounds)
7. PROPOSAL COLLECTION: Gather proposals from tool calls
8. RESPONSE: Return content + proposals + token_usage to caller
```

**Key Characteristics:**
- Everything is a synchronous Python import within one FastAPI process
- Tools are hardcoded in `ToolExecutor.__init__()` as a dictionary
- Course generation is sequential: page 1 → page 2 → page 3...
- HITL is polling-based: frontend calls `GET /job/{id}` repeatedly
- No agent separation — one orchestrator does planning, generation, and validation
- No graph abstraction — linear procedural code
- Telemetry is custom (X-Trace-ID), not OpenTelemetry
- Rate limiting is in-process (resets on restart)
- Safety is regex-only (no ML-based detection)
- File storage is local filesystem only (MinIO provisioned but not wired)

### 1.3 Current API Endpoints (44 AI Endpoints)

| Category | Endpoints | File |
|----------|-----------|------|
| Chat | POST /ai/chat, POST /ai/chat/stream, GET /ai/chat/history | `ai_chat.py` |
| Sessions | POST /ai/sessions, GET /ai/sessions/{id}, DELETE /ai/sessions/{id} | `ai_sessions.py` |
| Proposals | POST /ai/proposals, GET /ai/proposals, GET /ai/proposals/{id}, POST apply/cancel, POST delete-page, POST confirm-delete | `ai_proposals.py` |
| Confirmations | POST /ai/proposals/{id}/confirm | `ai_confirmations.py` |
| Tools (11) | list_pages, fetch_page, validate_course, propose_create_page, propose_update_page, apply_page_proposal, apply_update_proposal, propose_delete_page, confirm_delete_page, query_similar_courses, validate | `ai_tools.py` |
| Ingestion | POST /ai/ingestions, GET /ai/ingestions/{id}, GET /ai/ingestions, POST propose-breakdown, POST review-plan, POST /ai/generate-course, GET /ai/generate-course/{id}, POST apply | `ai_ingestion.py` |
| Admin | GET /ai/admin/safety-events, safety-stats, audit-logs, audit-summary, audit-logs/course/{id} | `ai_admin.py` |
| Config | GET /ai/feature-status | `ai_config.py` |
| Templates | GET /ai/templates, GET /ai/templates/{type_key} | `ai_templates.py` |
| Similar | POST /ai/similar-courses | `ai_similar_courses.py` |
| Tracing | GET /ai/sessions/{id}/trace, trace/summary, DELETE trace | `ai_tracing.py` |
| Workflows | POST /api/v1/workflows, GET /{id}, POST cancel/retry, GET events, GET list | `workflows.py` |
| WebSocket | WS /ws/courses/{course_id}/collaborate | `ws_collaboration.py` |

### 1.4 Current Database Schema (AI-Relevant Tables)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `ai_sessions` | AI authoring session | session_id, user_id, course_id, org_id, status, ttl |
| `ai_proposals` | Mutation proposals | proposal_id, session_id, operation, status, base_hash, confirmation_token_hash |
| `ai_confirmation_tokens` | Destructive-op tokens | token_hash, proposal_id, session_id, user_id, ttl |
| `ai_audit_logs` | Append-only audit trail | operation, actor_id, before_state, after_state, trace_id |
| `ai_outbox_events` | Transactional outbox | event_type, payload, retry_count, published |
| `ai_chat_turns` | Conversation history | session_id, user_prompt, assistant_response, model, token_usage |
| `ai_idempotency_keys` | Exactly-once keys | idempotency_key, response_cache, ttl |
| `ai_ingestion_jobs` | Document import jobs | job_id, session_id, status, extracted_sections, metadata |
| `ai_safety_events` | Safety guard actions | event_type, severity, session_id, sanitized_content |
| `ai_admin_overrides` | Admin bypass audit | admin_id, proposal_id, reason, timestamp |
| `workflow_type_definitions` | Workflow registry | workflow_type, state_definitions (JSONB) |
| `workflow_jobs` | Workflow job records | job_id, workflow_type, state, checkpoint, heartbeat, priority |
| `workflow_job_events` | Workflow event log | job_id, event_type, payload, timestamp |
| `course_embeddings` | Vector embeddings | course_record_id, embedding (Vector 1536 or JSONB), content_hash |

### 1.5 Current Infrastructure (docker-compose.yml)

| Service | Image | Port | Status |
|---------|-------|------|--------|
| PostgreSQL 16 + pgvector | `pgvector/pgvector:pg16` | 5432 | ✅ Active |
| Redis 7 | `redis:7-alpine` | 6379 | ✅ Active (caching + pub/sub only) |
| Redpanda (Kafka) | `redpanda:v24.1.1` | 19092 | ✅ Active (event streaming) |
| MinIO | `minio/minio:latest` | 9000/9001 | ⚠️ Provisioned, NOT wired in Python code |

---

## PART 2: INTENDED STATE (What We're Building)

### 2.1 Target Architecture: Pragmatic Multi-Agent System

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 1 — API Gateway (KEEP)                  │
│  FastAPI + Pydantic v2 | JWT Auth | SSE Streaming | Rate Limit  │
│  KEEP: All 44 existing endpoints. ADD: workflow progress SSE.   │
│  UPGRADE: Rate limiting to Redis-backed store.                  │
└─────────────────────────────────────────────────────────────────┘
                                │
┌───────────────────────────────┼─────────────────────────────────┐
│                    LAYER 2 — Agentic Core (NEW)                  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         LangGraph StateGraph (Course Generation Only)     │   │
│  │                                                          │   │
│  │  Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ [HITL-1:interrupt] │   │
│  │  (Validate)  (Extract)  (Plan)      (Plan Approval)      │   │
│  │     │                                                  │   │
│  │     └──→ Phase 4 ──→ Phase 5 ──→ Phase 6 ──→ Phase 7   │   │
│  │          (RAG)       (Select)     (Generate)  (Validate) │   │
│  │                              │                           │   │
│  │  [Parallel Fan-Out] ←────────┘                           │   │
│  │  Redis Streams: 1 msg/page, N workers consume            │   │
│  │                              │                           │   │
│  │  Phase 8 ──→ [HITL-2:interrupt] ──→ Phase 9              │   │
│  │  (Preview)  (Final Confirmation)    (Persist)            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         3 Specialist LLM Agents (NEW)                     │   │
│  │                                                          │   │
│  │  AGT-03 PLANNER AGENT          AGT-06 TEMPLATE SELECTOR  │   │
│  │  • Model: Planner tier          • Model: Planner tier     │   │
│  │  • Temp: 0.3                    • Temp: 0.2               │   │
│  │  • Task: Page breakdown         • Task: Per-page template │   │
│  │  • Orphan detection loop        • Hybrid: rules + LLM     │   │
│  │                                                          │   │
│  │  AGT-07 CONTENT GENERATOR (parallel instances)            │   │
│  │  • Model: Generator tier        • Temp: 0.7               │   │
│  │  • Task: Full page content      • JSON repair integrated  │   │
│  │  • Fan-out via Redis Streams    • Per-page retry (3×)    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         3 MCP Tool Servers (NEW — independently deployed) │   │
│  │                                                          │   │
│  │  content-writer-mcp          safety-scan-mcp              │   │
│  │  • LLM content generation     • Input/output/PII scanning │   │
│  │  • Independent scaling        • NeMo Guardrails (future)  │   │
│  │                                                          │   │
│  │  template-registry-mcp                                    │   │
│  │  • Template schema retrieval  • Independent updates       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  KEEP as in-process services (NOT agents, NOT MCP):             │
│  • IngestionService, DocumentExtractor, SimilarCourseService    │
│  • CourseAssembler, JSONRepair, CostTracker, ProposalService    │
│  • AuditService, OutboxService, IdempotencyService              │
└─────────────────────────────────────────────────────────────────┘
                                │
┌───────────────────────────────┼─────────────────────────────────┐
│                    LAYER 3 — Data & Infrastructure               │
│                                                                  │
│  KEEP: PostgreSQL + pgvector + Redis + Redpanda + MinIO         │
│  ADD: OpenTelemetry (replace custom telemetry)                   │
│  ADD: Prometheus /metrics endpoint                               │
│  ADD: S3Storage (wire MinIO — already provisioned)               │
│  ADD: RedisRateLimitStore (replace in-process store)             │
│  ADD: Redis Streams for parallel fan-out                         │
│  ADD: Langfuse (after OTel migration)                            │
│  ADD: NeMo Guardrails as second-line safety (after MCP)          │
│  DEFER: Kubernetes (until MCP extraction creates 3+ services)    │
│  DEFER: A2A Protocol (until non-Python agents needed)            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 What We ARE Building (The Pragmatic Scope)

| # | Component | Why | Priority |
|---|-----------|-----|----------|
| 1 | **LangGraph for course generation pipeline** | Enables parallel branches, HITL interrupts, checkpointing | CRITICAL |
| 2 | **3 specialist LLM agents** (Planner, Template Selector, Content Generator) | Specialised prompts improve quality. 3 agents gives 80% of benefit at 30% of complexity | HIGH |
| 3 | **Redis Streams fan-out** for parallel page generation | 30-page course drops from 8-15 min to 1-2 min | CRITICAL |
| 4 | **LangGraph interrupt() for HITL** | Replace polling with zero-cost graph suspension + push notifications | HIGH |
| 5 | **3 MCP servers** (content-writer, safety-scan, template-registry) | Independent scaling where it matters | MEDIUM |
| 6 | **OpenTelemetry** (replace custom telemetry) | Industry standard. Prerequisite for Langfuse, Grafana | CRITICAL |
| 7 | **Redis-backed rate limiting** | Survives restarts, works across workers | MEDIUM |
| 8 | **MinIO/S3 wiring** | Files survive container restarts | HIGH |
| 9 | **Prometheus metrics + Grafana** | Dashboards, alerting | MEDIUM |
| 10 | **Langfuse** (LLM observability) | Cost tracking, prompt versioning | MEDIUM |
| 11 | **NeMo Guardrails** as second-line safety | ML-based semantic detection | MEDIUM |
| 12 | **Workflow progress SSE** | Real-time generation progress | LOW |

### 2.3 What We Are NOT Building (Deferred)

| # | Component | Why Deferred | When to Revisit |
|---|-----------|-------------|-----------------|
| 1 | All 9 agents | 5 are deterministic services that gain nothing from being "agents" | Never — keep as services |
| 2 | All 9 MCP servers | 6 are latency-sensitive or too simple to justify MCP overhead | When independent scaling needed |
| 3 | A2A Protocol | All agents are Python in same codebase. A2A = overhead without benefit | When non-Python agents added |
| 4 | Kubernetes + HPA | Current Render.com/Docker deployment is appropriate for 1-5 services | When 3+ MCP servers need independent scaling + 100+ concurrent generations |
| 5 | LangGraph for chat | Chat is inherently linear. LangGraph adds complexity without value for chat | Never — keep ChatOrchestrator for chat |
| 6 | Mobile App / Web Frontend | Out of scope (backend only) | Separate project |

---

## PART 3: DETAILED WORKFLOW SPECIFICATIONS

### 3.1 Full Course From Uploaded File (The Primary Workflow)

**Current State Flowchart:** `docs/AI_Implemenation/01_SystemArchitecture/Full_Course_From_Uploaded_File_Scenario_Flow.mmd`

**Current State (Sequential):**
```
Phase 0: Upload → validate file → create import job (status=uploaded)
Phase 1: Extract PDF/DOCX → normalize sections → persist preview
Phase 2: LLM segmenter → generate page plan → validate plan → frontend review
Phase 3 (HITL): User edits/approves plan → POLLING: GET /job/{id} repeatedly
Phase 4: Generate content (SEQUENTIAL: page 1, page 2, ... page N)
Phase 5: Batch apply → atomic transaction → audit → outbox events
```

**Intended State (LangGraph + Parallel):**
```
Phase 0 (validate_input):     AGT-01 IngestionService — validate file, SHA-256 dedup
Phase 1 (extract):            DocumentExtractor — PDF/DOCX → sections, assets
Phase 2 (plan):               AGT-03 PLANNER AGENT — LLM page breakdown, orphan detection
Phase 3 (hitl_plan_approval): LangGraph interrupt() — SUSPEND, notify, wait (72h timeout)
Phase 4 (rag_retrieve):       SimilarCourseService — 3-tier retrieval for context
Phase 5 (select_templates):   AGT-06 TEMPLATE SELECTOR — per-page template (parallel via Redis Streams)
Phase 6 (generate_content):   AGT-07 CONTENT GENERATOR × N instances — parallel via Redis Streams
Phase 7 (validate):           ValidationEngine + SafetyService — JSON, safety, SCORM, a11y
Phase 8 (hitl_final_confirm): LangGraph interrupt() — SUSPEND, full preview, confirm (72h timeout)
Phase 9 (persist):            CourseAssembler — atomic create, audit, outbox
```

**LangGraph StateGraph Definition:**
```python
from typing import TypedDict, List, Optional, Annotated
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import interrupt, Send
import operator

class CourseGenerationState(TypedDict):
    # Input
    job_id: str
    session_id: str
    user_id: str
    file_path: str
    file_hash: str

    # Phase outputs (Annotated for reducer semantics)
    extracted_sections: Optional[List[dict]]
    page_plan: Optional[List[dict]]
    plan_approved: bool
    rag_context: Optional[List[dict]]
    template_assignments: Annotated[list, operator.add]  # Parallel fan-out results
    generated_pages: Annotated[list, operator.add]       # Parallel fan-out results
    validation_results: Optional[dict]
    final_approved: bool

    # Control
    current_phase: str
    errors: Annotated[list, operator.add]
    hitl_decision: Optional[str]  # "approve" | "edit" | "reject"

# Node functions
async def node_validate_input(state: CourseGenerationState) -> dict:
    """Phase 0: Validate file, create ingestion job."""
    ...

async def node_extract(state: CourseGenerationState) -> dict:
    """Phase 1: Extract PDF/DOCX → sections."""
    ...

async def node_plan(state: CourseGenerationState) -> dict:
    """Phase 2: AGT-03 Planner Agent → page breakdown."""
    ...

async def node_hitl_plan_approval(state: CourseGenerationState) -> dict:
    """Phase 3: LangGraph interrupt() — wait for human plan approval."""
    decision = interrupt({
        "phase": "plan_approval",
        "plan": state["page_plan"],
        "message": "Review the page plan. Approve, edit, or reject."
    })
    return {"hitl_decision": decision, "plan_approved": decision == "approve"}

async def node_rag_retrieve(state: CourseGenerationState) -> dict:
    """Phase 4: Retrieve similar courses, template schemas, component registry."""
    ...

async def node_select_templates_fanout(state: CourseGenerationState) -> list[Send]:
    """Phase 5: Fan-out — one message per page to Redis Streams."""
    return [
        Send("select_template_for_page", {"page": page, "job_id": state["job_id"]})
        for page in state["page_plan"]
    ]

async def node_select_template_for_page(state: dict) -> dict:
    """Phase 5 (worker): AGT-06 selects template for one page."""
    ...

async def node_generate_content_fanout(state: CourseGenerationState) -> list[Send]:
    """Phase 6: Fan-out — one message per page to Redis Streams."""
    return [
        Send("generate_page_content", {
            "page": page,
            "template": state["template_assignments"][i],
            "rag_context": state["rag_context"],
            "job_id": state["job_id"],
        })
        for i, page in enumerate(state["page_plan"])
    ]

async def node_generate_page_content(state: dict) -> dict:
    """Phase 6 (worker): AGT-07 generates content for one page."""
    ...

async def node_validate(state: CourseGenerationState) -> dict:
    """Phase 7: Validate all generated pages."""
    ...

async def node_hitl_final_confirm(state: CourseGenerationState) -> dict:
    """Phase 8: LangGraph interrupt() — wait for final confirmation."""
    decision = interrupt({
        "phase": "final_confirmation",
        "course_preview": state["generated_pages"],
        "validation": state["validation_results"],
        "message": "Review the generated course. Confirm or request changes."
    })
    return {"hitl_decision": decision, "final_approved": decision == "confirm"}

async def node_persist(state: CourseGenerationState) -> dict:
    """Phase 9: Atomic create — Course + Pages + Components in one transaction."""
    ...

# Build graph
builder = StateGraph(CourseGenerationState)

# Add nodes
builder.add_node("validate_input", node_validate_input)
builder.add_node("extract", node_extract)
builder.add_node("plan", node_plan)
builder.add_node("hitl_plan_approval", node_hitl_plan_approval)
builder.add_node("rag_retrieve", node_rag_retrieve)
builder.add_node("select_templates_fanout", node_select_templates_fanout)
builder.add_node("select_template_for_page", node_select_template_for_page)
builder.add_node("generate_content_fanout", node_generate_content_fanout)
builder.add_node("generate_page_content", node_generate_page_content)
builder.add_node("validate", node_validate)
builder.add_node("hitl_final_confirm", node_hitl_final_confirm)
builder.add_node("persist", node_persist)

# Add edges
builder.set_entry_point("validate_input")
builder.add_edge("validate_input", "extract")
builder.add_edge("extract", "plan")
builder.add_edge("plan", "hitl_plan_approval")
builder.add_conditional_edges("hitl_plan_approval", lambda s: s["plan_approved"], {
    True: "rag_retrieve",
    False: END,  # User rejected — job cancelled
})
builder.add_edge("rag_retrieve", "select_templates_fanout")
builder.add_conditional_edges("select_templates_fanout", lambda s: s["page_plan"], {})  # Fan-out
builder.add_edge("select_template_for_page", "generate_content_fanout")
builder.add_conditional_edges("generate_content_fanout", lambda s: s["page_plan"], {})  # Fan-out
builder.add_edge("generate_page_content", "validate")
builder.add_conditional_edges("validate", lambda s: len(s.get("errors", [])) == 0, {
    True: "hitl_final_confirm",
    False: "plan",  # Re-plan on validation failure
})
builder.add_conditional_edges("hitl_final_confirm", lambda s: s["final_approved"], {
    True: "persist",
    False: "plan",  # Re-plan if user requests changes
})
builder.add_edge("persist", END)

# Compile with PostgreSQL checkpointing
checkpointer = PostgresSaver.from_conn_string(os.getenv("DATABASE_URL"))
graph = builder.compile(checkpointer=checkpointer)
```

### 3.2 Chat Edit Workflow (KEEP Current Architecture)

**Current State Flowchart:** `docs/AI_Implemenation/01_SystemArchitecture/Simple_Chat_Edit_Scenario_Flow.mmd`

**Decision:** Keep `ChatOrchestrator` as-is. Chat is inherently linear (user message → LLM → tool calls → response → user message). LangGraph would add complexity without value.

**Changes needed:**
- Add `ModelTierRouter` integration (classify task → route to planner or generator model)
- Add `CostTracker` integration (record cost after each LLM call)
- Add `context_prune` trace span
- Add `model_routing` trace span
- Real SSE streaming via `process_message_stream()` instead of pseudo-chunking

**Keep unchanged:**
- `run_llm_loop()` structure
- Tool call execution
- Proposal collection
- Safety checks
- Context pruning logic
- Session management

### 3.3 RAG / Similar Course Retrieval Workflow

**Current State Flowchart:** `docs/AI_Implemenation/01_SystemArchitecture/Similar_Course_Retrieval_Flow.mmd`

**Current:** 3-tier fallback (pgvector → fulltext → keyword). Well-architected. Functional but:
- Only indexes courses, not templates or components
- pgvector extension may not be installed (G-05 in TPO TRD)
- Mock embeddings used instead of real OpenAI embeddings (G-06)
- No per-tier DB operation tracing (G-08)
- Only 1 similar course seeded (G-10)

**Changes needed:**
1. Install pgvector extension via Alembic migration
2. Switch `EMBEDDING_PROVIDER=openai` in production config
3. Add `db_operation` spans per tier (search_vector, search_fulltext, search_keyword, enrich_results)
4. Seed 5-10 diverse courses with embeddings
5. Extend RAG index to include template schemas + component type registry + API tool schemas (Unified SemanticIndex)

### 3.4 Propose-Validate-Confirm-Apply Safety Flow

**Current State Flowchart:** `docs/AI_Implemenation/01_SystemArchitecture/Propose_Validate_Confirm_Apply_Safety_Flow.mmd`

**Current:** Strong propose-before-apply pattern. Production-grade. KEEP AS-IS.

**No changes needed.** This is a strength, not a gap.

### 3.5 File Ingestion / Document Import Flow

**Current State Flowchart:** `docs/AI_Implemenation/01_SystemArchitecture/File_Ingestion_Document_Import_Flow.mmd`

**Current:** Functional. PDF/DOCX extraction via pdfplumber/python-docx. Local filesystem storage only.

**Changes needed:**
1. Wire MinIO/S3 storage: implement `S3Storage` class implementing `AbstractStorage`
2. Configurable via `STORAGE_BACKEND` env var (`local` or `s3`)

---

## PART 4: THE 3 SPECIALIST LLM AGENTS — DETAILED SPECIFICATIONS

### 4.1 AGT-03: Planner Agent

**File:** `app/services/ai/agents/planner_agent.py` (NEW)

```python
"""
AGT-03: Planner Agent
Phase 2 of course generation pipeline.
Task: AI page breakdown from extracted document sections.
Model: Planner tier (deepseek-v4-flash or claude-haiku-4-20250514)
Temperature: 0.3
"""

PLANNER_SYSTEM_PROMPT = """You are an expert instructional designer and curriculum planner.
Your job is to analyze extracted document sections and produce an optimal page breakdown
for an e-learning course.

RULES:
1. Each page must map to exactly one allowed template type from the whitelist.
2. Every source section must be assigned to at least one page (no orphan content).
3. Pages should follow a logical pedagogical sequence (intro → modules → assessment).
4. Each page should have a focused learning objective derived from its source material.
5. Maximum 50 pages. If source material is very large, prioritize and group strategically.
6. Consider cognitive load: 3-7 concepts per page maximum.
7. Flag sections that cannot be reasonably assigned to any template (orphans).

ALLOWED TEMPLATE TYPES (from template-registry):
- content-text: Standard text-based lesson page with rich HTML content
- tabs: Multi-tab layout for comparing concepts or presenting phases
- accordion: Expandable Q&A or topic drill-down format
- click-reveal: Interactive reveal elements for engagement
- final-assessment: Quiz page with MCQs, passing score, and feedback

OUTPUT FORMAT:
Return valid JSON:
{
  "pages": [
    {
      "title": "Page title derived from content",
      "template_type": "content-text",
      "source_sections": ["section_id_1", "section_id_2"],
      "learning_objective": "What the learner will know after this page",
      "rationale": "Why this template fits this content",
      "estimated_duration_minutes": 5
    }
  ],
  "orphans": [
    {
      "section_id": "section_id_x",
      "content_summary": "Brief summary of orphaned content",
      "reason": "Why it couldn't be assigned"
    }
  ],
  "coverage_report": {
    "total_sections": 42,
    "assigned_sections": 40,
    "orphan_sections": 2,
    "total_pages": 12
  }
}
"""

class PlannerAgent:
    """AGT-03: Specialised agent for course page planning."""

    def __init__(self, llm_client: LLMClient, model_tier_router: ModelTierRouter):
        self.client = llm_client
        self.router = model_tier_router
        self.max_retries = 2

    async def generate_page_plan(
        self,
        extracted_sections: list[dict],
        template_whitelist: list[str],
        course_context: dict,
    ) -> dict:
        """Generate a page breakdown plan from extracted document sections.

        Args:
            extracted_sections: List of {id, heading, content, level} dicts
            template_whitelist: Allowed template types
            course_context: {title, description, audience, tone}

        Returns:
            {pages: [...], orphans: [...], coverage_report: {...}}
        """
        prompt = self._build_planning_prompt(
            extracted_sections, template_whitelist, course_context
        )

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.chat(
                    messages=[LLMMessage(role="user", content=prompt)],
                    system_prompt=PLANNER_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_tokens=4096,
                )
                plan = self._parse_plan(response.content)
                # Validate coverage (no orphan sections missed)
                validation = self._validate_plan(plan, extracted_sections)
                if validation["valid"]:
                    return plan
                # Retry with validation feedback
                prompt = self._build_retry_prompt(prompt, validation["errors"])
            except Exception as exc:
                if attempt == self.max_retries:
                    raise
                logger.warning("Planner attempt %d failed: %s", attempt + 1, exc)

        raise PlannerError("PLAN_VALIDATION_FAILED", "Plan validation failed after retries")

    def _build_planning_prompt(self, sections, templates, context) -> str:
        """Build the planning prompt with structured section data."""
        sections_text = "\n".join(
            f"[{s['id']}] H{s.get('level',2)}: {s['heading']}\n{s['content'][:500]}"
            for s in sections
        )
        return f"""COURSE CONTEXT:
Title: {context.get('title', 'Untitled Course')}
Audience: {context.get('audience', 'adult learners')}
Tone: {context.get('tone', 'professional')}

ALLOWED TEMPLATES: {', '.join(templates)}

EXTRACTED SECTIONS:
{sections_text}

TASK: Generate an optimal page breakdown plan. See system prompt for rules and output format."""

    def _parse_plan(self, llm_output: str) -> dict:
        """Parse LLM JSON output with repair fallback."""
        from app.services.ai.json_repair import repair_json
        import json as _json

        # Extract JSON from markdown code blocks
        content = llm_output
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            return _json.loads(content)
        except _json.JSONDecodeError:
            repaired = repair_json(content)
            return _json.loads(repaired)

    def _validate_plan(self, plan: dict, sections: list[dict]) -> dict:
        """Validate that all sections are covered."""
        assigned = set()
        for page in plan.get("pages", []):
            for sid in page.get("source_sections", []):
                assigned.add(sid)

        all_sections = {s["id"] for s in sections}
        missing = all_sections - assigned
        errors = []
        if missing:
            errors.append(f"Unassigned sections: {missing}")
        return {"valid": len(errors) == 0, "errors": errors}

    def _build_retry_prompt(self, original: str, errors: list[str]) -> str:
        return (
            f"Your previous plan had these issues:\n"
            + "\n".join(f"- {e}" for e in errors)
            + f"\n\nPlease revise. Original prompt:\n{original}"
        )
```

### 4.2 AGT-06: Template Selector Agent

**File:** `app/services/ai/agents/template_selector_agent.py` (NEW)

```python
"""
AGT-06: Template Selector Agent
Phase 5 of course generation pipeline.
Task: Select optimal template for each page (hybrid: rules + LLM).
Model: Planner tier (deepseek-v4-flash)
Temperature: 0.2
"""

# Rule-based classifier: handles ~85% of cases deterministically
TEMPLATE_RULES = {
    "assessment": {
        "keywords": ["quiz", "test", "assessment", "exam", "check your knowledge",
                      "evaluate", "score", "passing", "questions", "mcq"],
        "template": "final-assessment",
        "confidence": 0.95,
    },
    "comparison": {
        "keywords": ["compare", "contrast", "versus", "vs", "differences",
                      "similarities", "pros and cons", "advantages"],
        "template": "tabs",
        "confidence": 0.90,
    },
    "faq": {
        "keywords": ["faq", "frequently asked", "common questions",
                      "q&a", "questions and answers"],
        "template": "accordion",
        "confidence": 0.90,
    },
    "interactive": {
        "keywords": ["interactive", "click", "reveal", "explore", "discover",
                      "drag", "flip", "card"],
        "template": "click-reveal",
        "confidence": 0.85,
    },
    "video": {
        "keywords": ["video", "watch", "animation", "demonstration",
                      "screencast", "walkthrough"],
        "template": "content-text",  # content-text with embedded video
        "confidence": 0.80,
    },
}

TEMPLATE_SELECTOR_SYSTEM_PROMPT = """You are an e-learning template selection expert.
Given a page plan entry and its source content, select the most appropriate template type.

TEMPLATE TYPES:
- content-text: Rich text page with headings, paragraphs, images, videos, callouts
- tabs: Multi-tab layout for comparing concepts, phases, or perspectives
- accordion: Expandable sections for Q&A, drill-downs, or detailed topics
- click-reveal: Interactive reveal elements for engagement and self-checks
- final-assessment: Quiz with MCQs, passing score, and answer feedback

OUTPUT: Return JSON: {"template_type": "...", "confidence": 0.0-1.0, "reasoning": "..."}"""


class TemplateSelectorAgent:
    """AGT-06: Hybrid template selector — rules first, LLM for edge cases."""

    def __init__(self, llm_client: LLMClient):
        self.client = llm_client
        self.confidence_threshold = 0.80  # Below this, use LLM

    async def select_template(self, page: dict, source_content: str) -> dict:
        """Select the optimal template for a page.

        Hybrid approach:
        1. Apply deterministic keyword rules (covers ~85% of cases)
        2. If rule confidence < threshold, fall back to LLM
        3. Return {template_type, confidence, reasoning, method}
        """
        # Step 1: Try rules
        rule_result = self._classify_by_rules(page, source_content)
        if rule_result and rule_result["confidence"] >= self.confidence_threshold:
            return {**rule_result, "method": "rule"}

        # Step 2: Fall back to LLM
        llm_result = await self._classify_by_llm(page, source_content)
        return {**llm_result, "method": "llm"}

    def _classify_by_rules(self, page: dict, source_content: str) -> dict | None:
        """Apply keyword rules. Returns None if no rule matches."""
        combined = f"{page.get('title', '')} {page.get('learning_objective', '')} {source_content}"
        combined_lower = combined.lower()

        best_match = None
        best_confidence = 0

        for rule_name, rule in TEMPLATE_RULES.items():
            matches = sum(1 for kw in rule["keywords"] if kw in combined_lower)
            if matches > 0:
                weighted_confidence = rule["confidence"] * min(matches / len(rule["keywords"]), 1.0)
                if weighted_confidence > best_confidence:
                    best_confidence = weighted_confidence
                    best_match = {
                        "template_type": rule["template"],
                        "confidence": round(weighted_confidence, 2),
                        "reasoning": f"Rule '{rule_name}' matched {matches}/{len(rule['keywords'])} keywords",
                    }

        return best_match

    async def _classify_by_llm(self, page: dict, source_content: str) -> dict:
        """LLM-based template selection for edge cases."""
        prompt = f"""Page Title: {page.get('title', '')}
Learning Objective: {page.get('learning_objective', '')}
Source Content: {source_content[:1000]}

Select the best template type for this page."""

        response = await self.client.chat(
            messages=[LLMMessage(role="user", content=prompt)],
            system_prompt=TEMPLATE_SELECTOR_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=256,
        )
        return self._parse_selection(response.content)

    def _parse_selection(self, llm_output: str) -> dict:
        import json as _json
        try:
            content = llm_output
            if "```" in content:
                content = content.split("```")[1].split("```")[0]
            return _json.loads(content)
        except Exception:
            return {"template_type": "content-text", "confidence": 0.5,
                    "reasoning": "Default fallback — LLM output unparseable"}
```

### 4.3 AGT-07: Content Generator Agent

**File:** `app/services/ai/agents/content_generator_agent.py` (NEW)

```python
"""
AGT-07: Content Generator Agent
Phase 6 of course generation pipeline.
Task: Generate full educational content for a single page.
Model: Generator tier (deepseek-v4-pro[1m] or claude-sonnet-4-20250514)
Temperature: 0.7
Parallel: N instances via Redis Streams consumer group
Retry: Per-page retry (3× max) with JSON repair on each attempt
"""

GENERATOR_SYSTEM_PROMPT = """You are an expert instructional designer and e-learning content creator.
Generate high-quality, pedagogically sound educational content in valid JSON format.

CONTENT QUALITY RULES:
1. Write for the target audience — use appropriate language complexity.
2. Ground all facts in the provided source material. Do NOT fabricate information.
3. Use clear headings, short paragraphs, bullet points, and examples.
4. For assessments: plausible distractors, clear correct answers, constructive feedback.
5. For interactive elements: engaging prompts, progressive disclosure, scenario-based.
6. Do NOT include answer keys (isCorrect) in sample/example content.
7. Follow the template schema EXACTLY — every required field must be present.
8. Format output as clean, parseable JSON inside a markdown code block.

TEMPLATE-SPECIFIC GUIDANCE:
- content-text: 3-5 substantive paragraphs, relevant headings, 1-2 callout boxes
- tabs: 3-4 tabs with balanced content, clear tab labels
- accordion: 4-6 items, progressive difficulty, clear trigger text
- click-reveal: 3-5 reveal cards, engaging prompts, valuable revealed content
- final-assessment: 5-10 MCQs covering key learning objectives, plausible distractors, passing_score: 80"""


class ContentGeneratorAgent:
    """AGT-07: Generates full page content via LLM.

    Designed for parallel execution: one instance per page, coordinated via Redis Streams.
    """

    def __init__(self, llm_client: LLMClient, json_repair: JSONRepair, max_retries: int = 3):
        self.client = llm_client
        self.json_repair = json_repair
        self.max_retries = max_retries

    async def generate_page(
        self,
        page_plan: dict,
        template_assignment: dict,
        rag_context: list[dict],
        course_context: dict,
        page_index: int,
        total_pages: int,
    ) -> dict:
        """Generate full educational content for a single page.

        Args:
            page_plan: Page plan entry {title, learning_objective, source_sections, template_type}
            template_assignment: Template selection result {template_type, confidence, reasoning}
            rag_context: Similar courses/examples for tone/style reference
            course_context: {title, description, audience, tone}
            page_index: Zero-based page index
            total_pages: Total pages in course

        Returns:
            {title, template_type, order, components: [...], source_excerpt, generation_metadata}
        """
        template_type = template_assignment["template_type"]
        prompt = self._build_generation_prompt(
            page_plan, template_type, rag_context, course_context,
            page_index, total_pages
        )

        for attempt in range(self.max_retries):
            try:
                response = await self.client.chat(
                    messages=[LLMMessage(role="user", content=prompt)],
                    system_prompt=GENERATOR_SYSTEM_PROMPT,
                    temperature=0.7,
                    max_tokens=4096,
                )
                parsed = self._parse_and_repair(response.content, template_type)

                # Quick validation
                if self._quick_validate(parsed, template_type):
                    return {
                        "title": page_plan.get("title", f"Page {page_index + 1}"),
                        "template_type": template_type,
                        "order": page_plan.get("order", page_index),
                        "components": parsed.get("components", []),
                        "source_excerpt": page_plan.get("source_content", "")[:500],
                        "learning_objective": page_plan.get("learning_objective", ""),
                        "generation_metadata": {
                            "attempt": attempt + 1,
                            "model": self.client.model,
                            "tokens_used": response.token_usage,
                        },
                    }

                # Retry with error feedback
                prompt = self._build_retry_prompt(
                    prompt, f"Invalid structure for template '{template_type}': missing required fields"
                )

            except Exception as exc:
                logger.error("Generator attempt %d for page %d failed: %s",
                           attempt + 1, page_index, exc)
                if attempt == self.max_retries - 1:
                    # Last attempt failed — return mock fallback for this page
                    return self._generate_mock_fallback(page_plan, page_index)

        # Shouldn't reach here, but safety fallback
        return self._generate_mock_fallback(page_plan, page_index)

    def _build_generation_prompt(self, page_plan, template_type, rag_context,
                                  course_context, page_index, total_pages) -> str:
        """Build template-specific generation prompt."""
        # Template-specific JSON schemas
        schemas = {
            "content-text": {
                "components": [{
                    "component_type": "content-text",
                    "order_index": 0,
                    "data": {
                        "content": "<h2>Title</h2><p>Body with educational content...</p>"
                    }
                }]
            },
            "tabs": {
                "components": [{
                    "component_type": "tabs",
                    "order_index": 0,
                    "data": {
                        "tabs": [
                            {"title": "Tab 1", "content": "Content for tab 1..."},
                            {"title": "Tab 2", "content": "Content for tab 2..."},
                        ]
                    }
                }]
            },
            "accordion": {
                "components": [{
                    "component_type": "accordion",
                    "order_index": 0,
                    "data": {
                        "items": [
                            {"title": "Item 1", "content": "Expanded content..."},
                        ]
                    }
                }]
            },
            "click-reveal": {
                "components": [{
                    "component_type": "click-reveal",
                    "order_index": 0,
                    "data": {
                        "cards": [
                            {"prompt": "Click to reveal...", "content": "Revealed content..."},
                        ]
                    }
                }]
            },
            "final-assessment": {
                "components": [{
                    "component_type": "final-assessment",
                    "order_index": 0,
                    "data": {
                        "passing_score": 80,
                        "questions": [{
                            "id": "q-1",
                            "type": "mcq",
                            "question": "Question text?",
                            "options": [
                                {"id": "a", "text": "Correct answer", "isCorrect": True},
                                {"id": "b", "text": "Distractor 1", "isCorrect": False},
                                {"id": "c", "text": "Distractor 2", "isCorrect": False},
                                {"id": "d", "text": "Distractor 3", "isCorrect": False},
                            ],
                            "feedback": "Explanation of the correct answer."
                        }]
                    }
                }]
            },
        }

        schema = schemas.get(template_type, schemas["content-text"])
        schema_json = json.dumps(schema, indent=2)

        # RAG examples
        rag_examples = ""
        if rag_context:
            examples = rag_context[:2]  # Top 2 similar courses
            rag_examples = "\nSIMILAR COURSE EXAMPLES (for style/tone reference only):\n"
            for ex in examples:
                rag_examples += f"- {ex.get('title', '')}: {ex.get('excerpt', '')[:200]}\n"

        return f"""COURSE: {course_context.get('title', 'Untitled')} (Page {page_index + 1} of {total_pages})
PAGE TITLE: {page_plan.get('title', '')}
LEARNING OBJECTIVE: {page_plan.get('learning_objective', '')}
TEMPLATE TYPE: {template_type}
AUDIENCE: {course_context.get('audience', 'adult learners')}
TONE: {course_context.get('tone', 'professional')}

SOURCE MATERIAL:
{page_plan.get('source_content', '')[:2000]}

{rag_examples}

REQUIRED OUTPUT SCHEMA:
```json
{schema_json}
```

IMPORTANT:
- Generate 3-5 substantive educational paragraphs/items per component.
- Do NOT use placeholder text like 'lorem ipsum'.
- Content must be factually grounded in the source material above.
- For assessments: provide plausible distractor options — don't make wrong answers obvious.
- Return ONLY the JSON inside ```json ``` code block."""

    def _parse_and_repair(self, llm_output: str, template_type: str) -> dict:
        """Extract JSON from LLM output, repair if needed."""
        import json as _json

        content = llm_output
        # Extract from code block
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            return _json.loads(content)
        except _json.JSONDecodeError:
            # Run through 12-strategy repair pipeline
            repaired = self.json_repair.repair(content)
            return _json.loads(repaired)

    def _quick_validate(self, parsed: dict, template_type: str) -> bool:
        """Fast pre-validation — checks structure, not full schema."""
        if "components" not in parsed or not isinstance(parsed["components"], list):
            return False
        if len(parsed["components"]) == 0:
            return False
        comp = parsed["components"][0]
        if "component_type" not in comp or "data" not in comp:
            return False
        return True

    def _build_retry_prompt(self, original: str, error: str) -> str:
        return f"Your previous output had this issue: {error}\n\nPlease fix and regenerate.\n\n{original}"

    def _generate_mock_fallback(self, page_plan: dict, page_index: int) -> dict:
        """Deterministic mock fallback when LLM generation fails completely."""
        # Reuse existing CourseGenerator._generate_page_content() logic
        return {
            "title": page_plan.get("title", f"Page {page_index + 1}"),
            "template_type": page_plan.get("template_type", "content-text"),
            "order": page_index,
            "components": [{
                "component_type": "content-text",
                "order_index": 0,
                "data": {
                    "content": f"<h2>{page_plan.get('title', 'Content')}</h2>"
                              f"<p>Content for this section.</p>"
                }
            }],
            "source_excerpt": "",
            "learning_objective": page_plan.get("learning_objective", ""),
            "generation_metadata": {"fallback": True, "reason": "LLM generation failed"},
        }
```

---

## PART 5: REDIS STREAMS FAN-OUT — PARALLEL EXECUTION

### 5.1 Architecture

```
Supervisor (LangGraph node: generate_content_fanout)
    │
    ├── Publish 1 message per page to Redis Stream: course:generation:{job_id}
    │   Message: {page_index, page_plan, template, rag_context, course_context}
    │
    └── Consumer Group: content-generators
        ├── Worker 1 (asyncio task) ──→ AGT-07.generate_page(page_0) ──→ Results Stream
        ├── Worker 2 (asyncio task) ──→ AGT-07.generate_page(page_1) ──→ Results Stream
        ├── Worker 3 (asyncio task) ──→ AGT-07.generate_page(page_2) ──→ Results Stream
        └── Worker N (asyncio task) ──→ AGT-07.generate_page(page_n) ──→ Results Stream
                                            │
                                    Results Stream: course:generation:{job_id}:results
                                            │
                                    Supervisor collects all results
```

### 5.2 Implementation

**File:** `app/services/ai/fanout/stream_manager.py` (NEW)

```python
"""Redis Streams fan-out manager for parallel course generation.

Uses Redis Streams consumer groups for exactly-once processing.
Each page is a message. N workers consume concurrently.
Results are collected in a results stream.
"""

import asyncio
import json
import os
from typing import AsyncIterator
import redis.asyncio as redis


class StreamManager:
    """Manages Redis Streams for parallel page generation fan-out."""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis: redis.Redis | None = None
        self.max_concurrency = int(os.getenv("AI_GENERATION_CONCURRENCY", "3"))

    async def connect(self):
        self.redis = redis.from_url(self.redis_url, decode_responses=True)

    async def disconnect(self):
        if self.redis:
            await self.redis.close()

    async def fan_out_pages(
        self,
        job_id: str,
        pages: list[dict],
        templates: list[dict],
        rag_context: list[dict],
        course_context: dict,
        generate_func,  # AGT-07.generate_page
    ) -> list[dict]:
        """Fan out page generation to N concurrent workers via Redis Streams.

        Args:
            job_id: Unique job ID for stream naming
            pages: List of page plan entries
            templates: List of template assignments (same order as pages)
            rag_context: RAG context for all pages
            course_context: Course-level context
            generate_func: Async function (page, template, rag, ctx, idx, total) -> dict

        Returns:
            List of generated page dicts (in original order)
        """
        stream_key = f"course:generation:{job_id}"
        results_key = f"course:generation:{job_id}:results"
        group_name = f"generators-{job_id}"

        # Create consumer group
        try:
            await self.redis.xgroup_create(stream_key, group_name, id="0", mkstream=True)
        except redis.ResponseError:
            pass  # Group already exists

        # Publish pages as messages
        total = len(pages)
        for i, (page, template) in enumerate(zip(pages, templates)):
            await self.redis.xadd(stream_key, {
                "page_index": str(i),
                "total_pages": str(total),
                "page_plan": json.dumps(page),
                "template": json.dumps(template),
                "rag_context": json.dumps(rag_context),
                "course_context": json.dumps(course_context),
            })

        # Spawn N worker tasks
        semaphore = asyncio.Semaphore(self.max_concurrency)
        generated = [None] * total
        completed = 0

        async def worker():
            nonlocal completed
            while True:
                async with semaphore:
                    messages = await self.redis.xreadgroup(
                        group_name, f"worker-{id(asyncio.current_task())}",
                        {stream_key: ">"}, count=1, block=1000
                    )
                    if not messages:
                        break

                    for _, entries in messages:
                        for msg_id, data in entries:
                            idx = int(data["page_index"])
                            try:
                                result = await generate_func(
                                    page_plan=json.loads(data["page_plan"]),
                                    template_assignment=json.loads(data["template"]),
                                    rag_context=json.loads(data["rag_context"]),
                                    course_context=json.loads(data["course_context"]),
                                    page_index=idx,
                                    total_pages=int(data["total_pages"]),
                                )
                                generated[idx] = result
                            except Exception as exc:
                                generated[idx] = {"error": str(exc), "page_index": idx}
                            finally:
                                await self.redis.xack(stream_key, group_name, msg_id)
                                await self.redis.xadd(results_key, {
                                    "page_index": str(idx),
                                    "status": "error" if "error" in str(generated[idx]) else "success",
                                })
                                completed += 1

        # Run workers
        workers = [asyncio.create_task(worker()) for _ in range(self.max_concurrency)]
        await asyncio.gather(*workers, return_exceptions=True)

        # Cleanup
        await self.redis.delete(stream_key, results_key)

        return generated
```

---

## PART 6: MCP SERVER SPECIFICATIONS

### 6.1 content-writer-mcp

**Why extract:** Content generation is the bottleneck. Independent scaling lets us add GPU instances for generation without scaling the API.

**Tools exposed:**
```python
# MCP Tool: generate_page_content
{
    "name": "generate_page_content",
    "description": "Generate full educational content for a single e-learning page using LLM",
    "inputSchema": {
        "type": "object",
        "properties": {
            "page_plan": {"type": "object", "description": "Page plan with title, learning_objective, source_content"},
            "template_type": {"type": "string", "enum": ["content-text", "tabs", "accordion", "click-reveal", "final-assessment"]},
            "rag_context": {"type": "array", "description": "Similar course examples for tone/style reference"},
            "course_context": {"type": "object", "description": "Course-level context: title, audience, tone"},
            "page_index": {"type": "integer"},
            "total_pages": {"type": "integer"}
        },
        "required": ["page_plan", "template_type", "course_context"]
    }
}

# MCP Tool: health
{
    "name": "health",
    "description": "Health check with model availability and rate limit status",
    "inputSchema": {"type": "object", "properties": {}}
}
```

**Implementation:** Wrap `ContentGeneratorAgent` behind MCP server protocol. Deploy as separate FastAPI app or MCP server binary.

### 6.2 safety-scan-mcp

**Why extract:** Safety models evolve independently. Enable updates without redeploying the main app. Enable future NeMo integration.

**Tools exposed:**
```python
# MCP Tool: scan_input
{
    "name": "scan_input",
    "description": "Scan user input for injection, jailbreak, PII, and policy violations",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "maxLength": 10000},
            "user_id": {"type": "string"},
            "session_id": {"type": "string"}
        },
        "required": ["text"]
    }
}

# MCP Tool: scan_output
{
    "name": "scan_output",
    "description": "Scan AI-generated output for PII leaks, blocked terms, policy violations",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "maxLength": 50000},
            "session_id": {"type": "string"}
        },
        "required": ["text"]
    }
}
```

### 6.3 template-registry-mcp

**Why extract:** Templates change frequently during content design. Independent deployment enables template updates without app restart.

**Tools exposed:**
```python
# MCP Tool: list_templates
# MCP Tool: get_template_schema
# MCP Tool: validate_against_template
# MCP Tool: search_templates (semantic search for template discovery)
```

### 6.4 What Stays In-Process (NOT MCP)

These services are too simple or too latency-sensitive to justify MCP extraction:
- **file-store** — file I/O over network = slower, not safer
- **extraction** — CPU-bound library calls, network adds latency
- **pgvector** — database is already a network call, adding MCP doubles latency
- **course-db** — write latency is critical for transactions
- **audit-log** — synchronous audit writes, network adds failure modes
- **notification** — already async via outbox + Kafka

---

## PART 7: OPENTELEMETRY MIGRATION

### 7.1 Replace Custom Telemetry with OpenTelemetry

**Current:** `AITelemetryMiddleware` (`app/middleware/ai_telemetry.py`) — custom `X-Trace-ID` header, in-memory counters, proprietary format.

**Target:** OpenTelemetry SDK with W3C Trace Context propagation.

**Step 1: Add dependencies**
```bash
pip install opentelemetry-api opentelemetry-sdk
pip install opentelemetry-instrumentation-fastapi
pip install opentelemetry-instrumentation-sqlalchemy
pip install opentelemetry-instrumentation-redis
pip install opentelemetry-exporter-otlp
```

**Step 2: Initialize OTel in `app/main.py`**
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

def init_otel(app: FastAPI):
    """Initialize OpenTelemetry with OTLP exporter."""
    if not os.getenv("OTEL_ENABLED", "").lower() == "true":
        return

    provider = TracerProvider()
    exporter = OTLPSpanExporter(
        endpoint=os.getenv("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317"),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()
```

**Step 3: Create AI-specific tracer**
```python
# app/services/ai/otel_tracer.py (NEW)
from opentelemetry import trace

AI_TRACER = trace.get_tracer("ai-authoring")

async def trace_agent_call(agent_name: str, phase: str, input_data: dict):
    """Create an OTel span for an agent invocation."""
    with AI_TRACER.start_as_current_span(
        f"agent.{agent_name}",
        attributes={
            "agent.name": agent_name,
            "agent.phase": phase,
            "ai.input.type": input_data.get("type", "unknown"),
        }
    ) as span:
        # Agent logic here
        ...
```

**Step 4: Keep custom telemetry as fallback**
- Run OTel and custom telemetry in parallel for 2 weeks
- Validate traces match in both systems
- Then deprecate custom middleware

### 7.2 Add Prometheus /metrics Endpoint

```python
# app/monitoring/metrics.py (NEW)
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY
from fastapi import Response

# AI-specific metrics
ai_generation_counter = Counter(
    "ai_course_generations_total", "Total course generations",
    ["status"]  # "success", "failed", "cancelled"
)
ai_page_generation_duration = Histogram(
    "ai_page_generation_seconds", "Per-page generation duration",
    ["template_type"],
    buckets=[1, 2, 5, 10, 20, 30, 60, 120]
)
ai_llm_call_counter = Counter(
    "ai_llm_calls_total", "Total LLM API calls",
    ["model", "tier"]  # "deepseek-v4-pro", "generator"
)
ai_token_counter = Counter(
    "ai_tokens_total", "Total tokens consumed",
    ["model", "direction"]  # "input", "output"
)
ai_cost_counter = Counter(
    "ai_cost_usd_total", "Total USD cost",
    ["model"]
)

async def metrics_endpoint():
    return Response(content=generate_latest(REGISTRY), media_type="text/plain")
```

---

## PART 8: TPO GAP ANALYSIS — ALL 13 GAPS RESOLUTION

### Already Fixed (G-01 → G-04) — VERIFIED IN CODEBASE

| Gap | Description | Fix Location |
|-----|-------------|-------------|
| G-01 | State machine regression: `start_generation` reverted to `analyzed` | `course_generator.py:185` — `job.status = "generated"` |
| G-02 | Missing `page_plan_ready` state | `ai_ingestion.py:235` — new state + guard |
| G-03 | `propose-breakdown` rejected completed jobs | `ai_ingestion.py:162-177` — idempotent plan return |
| G-04 | RAG `end_span` crash: TypeError on `metadata` | `session_tracer.py:124` — added `metadata` param |

### To Be Fixed During Migration (G-05 → G-13)

| Gap | Description | Priority | Phase |
|-----|-------------|----------|-------|
| G-05 | pgvector extension not installed | P1 — Week 1 | Phase 0 |
| G-06 | Mock embeddings instead of OpenAI | P1 — Week 1 | Phase 0 |
| G-07 | Course generation uses mock (not LLM) | P2 — Week 3 | Phase 1 |
| G-08 | DB operations not traced | P1 — Week 2 | Phase 0 |
| G-09 | Context pruning not traced | P1 — Week 2 | Phase 0 |
| G-10 | Only 1 similar course in RAG | P2 — Week 3 | Phase 0 |
| G-11 | Streaming spans missing (pseudo-chunks) | P3 — Week 5 | Phase 2 |
| G-12 | Cost tracking not wired to orchestrator | P2 — Week 4 | Phase 1 |
| G-13 | Model tier router not used in chat flow | P2 — Week 4 | Phase 1 |

---

## PART 9: COURSE AUTHORING TOOL APIs (CURRENT + NEW)

### Existing Tools (KEEP — `app/routers/ai_tools.py`)

| Tool | Endpoint | Description |
|------|----------|-------------|
| list_pages | POST /ai/tools/list_pages | List all pages in session's course with metadata |
| fetch_page | POST /ai/tools/fetch_page | Fetch single page with full content + components |
| validate_course | POST /ai/tools/validate_course | Schema + business rules + accessibility validation |
| propose_create_page | POST /ai/tools/propose_create_page | Propose new page (no mutation) |
| propose_update_page | POST /ai/tools/propose_update_page | Propose page update (no mutation) |
| apply_page_proposal | POST /ai/tools/apply_page_proposal | Apply proposal with idempotency |
| apply_update_proposal | POST /ai/tools/apply_update_proposal | Apply update with staleness detection |
| propose_delete_page | POST /ai/tools/propose_delete_page | Propose deletion with dependency analysis + token |
| confirm_delete_page | POST /ai/tools/confirm_delete_page | Confirm + execute deletion |
| query_similar_courses | POST /ai/tools/query_similar_courses | RAG search (pgvector/fulltext/keyword) |
| validate | POST /ai/tools/validate | Standalone template data validation |

### New/Modified APIs for Multi-Agent Architecture

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/workflows/{job_id}/stream` | GET (SSE) | Real-time workflow progress events |
| `/api/v1/workflows/{job_id}/resume` | POST | Resume LangGraph after HITL interrupt |
| `/api/v1/courses/generate/parallel` | POST | Submit parallel generation job (Redis Streams) |
| `/api/v1/agent/planner/generate-plan` | POST | AGT-03: Generate page breakdown |
| `/api/v1/agent/selector/select-template` | POST | AGT-06: Select template for page |
| `/api/v1/agent/generator/generate-page` | POST | AGT-07: Generate page content |
| `/api/v1/mcp/content-writer/health` | GET | MCP server health check |
| `/api/v1/mcp/safety-scan/scan` | POST | MCP: Safety scan input/output |
| `/api/v1/mcp/template-registry/search` | POST | MCP: Semantic template search |
| `/api/v1/admin/metrics` | GET | Prometheus metrics endpoint |

---

## PART 10: LATEST AGENTIC AI BEST PRACTICES (June 2026)

### Patterns to Adopt

1. **Declarative Graph Orchestration (LangGraph)**
   - Define workflows as typed state graphs, not procedural code
   - Automatic checkpointing at every node boundary
   - Native `Send()` API for parallel fan-out
   - `interrupt()` for human-in-the-loop — zero compute cost while waiting

2. **Agent Specialization Over Generalization**
   - Each agent has ONE clear responsibility
   - Dedicated system prompts optimised for the specific task
   - Different temperature settings per agent (planning: 0.2-0.3, generation: 0.7-0.8)
   - Different model tiers per agent (planner: cheap/fast, generator: powerful/expensive)

3. **MCP for Cross-Boundary Tools**
   - Tools that need independent scaling → MCP server
   - Tools that need independent update lifecycles → MCP server
   - Simple, latency-sensitive tools → in-process service
   - Rule: MCP-ify only when the operational benefit exceeds the network cost

4. **Hybrid Rules + LLM Architecture**
   - Deterministic rules for ~85% of decisions (fast, cheap, consistent)
   - LLM for the remaining ~15% (edge cases, ambiguous inputs)
   - AGT-06 Template Selector is the canonical example

5. **DB-First State (Source of Truth)**
   - Every agent re-fetches state from DB before acting
   - Conversation history is NEVER trusted for current state
   - System prompt rebuilt each turn from DB state
   - This is already implemented — KEEP IT

6. **Propose-Before-Apply Mutation Gating**
   - AI proposes → system validates → human confirms → system applies
   - Confirmation tokens for destructive operations
   - Idempotency keys for exactly-once semantics
   - This is already implemented — KEEP IT

7. **Graceful Degradation at Every Boundary**
   - pgvector unavailable → full-text fallback
   - LLM rate limited → mock fallback
   - Redis down → DB polling fallback
   - MCP server down → in-process fallback
   - LangGraph unavailable → WorkflowOrchestrator fallback

8. **Observability-First Development**
   - Every agent call, LLM call, tool call, DB operation traced
   - OpenTelemetry as the standard (not custom tracing)
   - Metrics: RED (Rate, Errors, Duration) for every endpoint
   - Cost tracking per agent, per session, per user

### Anti-Patterns to Avoid

1. **Over-Decomposition:** Don't create an "agent" for deterministic logic. File validation is not an agent — it's a function.
2. **Protocol Over-Engineering:** Don't add A2A when direct function calls work. Protocol complexity is a cost, not a feature.
3. **Premature K8s:** Docker Compose + Render.com is sufficient until you have 3+ independently-scalable services.
4. **Vendor Lock-In:** Abstract LangGraph behind an internal orchestration interface. Keep `WorkflowOrchestrator` as fallback.
5. **Temperature Extremes:** Never use temp > 0.8 for content generation (hallucination risk) or temp < 0.1 for planning (repetitive outputs).
6. **Token Waste:** Don't send full conversation history to every agent. Each agent gets only the context it needs.

---

## PART 11: IMPLEMENTATION PLAN

### Phase 0: Foundation (Week 1-3) — CRITICAL PATH

| Task | File(s) | Effort | Depends On |
|------|---------|--------|------------|
| 0.1 Install pgvector extension + migration | `alembic/versions/xxxx_enable_pgvector.py` | 2h | — |
| 0.2 Switch to OpenAI embeddings | `.env`, `embedding_provider.py` | Config only | 0.1 |
| 0.3 Add OpenTelemetry SDK | `app/main.py`, `app/services/ai/otel_tracer.py` (NEW), `requirements.txt` | 3 days | — |
| 0.4 Add Prometheus /metrics endpoint | `app/monitoring/metrics.py` (NEW), `app/main.py` | 1 day | — |
| 0.5 Wire MinIO/S3 storage | `app/services/storage.py` (add S3Storage class), `requirements.txt` (+aiobotocore) | 3 days | — |
| 0.6 Redis-backed rate limiting | `app/middleware/ai_rate_limiter.py` (add RedisRateLimitStore) | 1 day | — |
| 0.7 Add DB operation tracing | `app/services/ai/similar_course_service.py` (add db_operation spans) | 2h | — |
| 0.8 Add context pruning tracing | `app/services/ai/chat_orchestrator.py` (add context_prune span) | 1h | — |
| 0.9 Seed 5-10 courses with embeddings | `tests/seed_rag_data.py` (enhance), `app/workers/embedding_worker.py` (NEW) | 2h | 0.1, 0.2 |

**Phase 0 Deliverable:** OTel traces visible. /metrics endpoint. S3 storage working. pgvector semantic search active.

### Phase 1: Speed (Week 4-7) — USER-VISIBLE IMPACT

| Task | File(s) | Effort | Depends On |
|------|---------|--------|------------|
| 1.1 Redis Streams fan-out manager | `app/services/ai/fanout/stream_manager.py` (NEW) | 3 days | Phase 0 |
| 1.2 AGT-07 Content Generator Agent | `app/services/ai/agents/content_generator_agent.py` (NEW) | 4 days | Phase 0 |
| 1.3 Wire course generation to LLM (G-07) | `app/services/ai/course_generator.py` (modify) | 2 days | 1.2 |
| 1.4 Parallel generation job endpoint | `app/routers/ai_ingestion.py` (add generate-parallel) | 1 day | 1.1, 1.2 |
| 1.5 Workflow progress SSE endpoint | `app/routers/workflows.py` (add /stream) | 1 day | — |
| 1.6 Wire CostTracker to orchestrator (G-12) | `app/services/ai/chat_orchestrator.py` | 1h | — |
| 1.7 Wire ModelTierRouter to orchestrator (G-13) | `app/services/ai/chat_orchestrator.py` | 2h | — |

**Phase 1 Deliverable:** 50-page course generation drops from 8-15 min to 1-2 min. Real-time progress visible.

### Phase 2: Intelligence (Week 8-15) — QUALITY IMPROVEMENT

| Task | File(s) | Effort | Depends On |
|------|---------|--------|------------|
| 2.1 LangGraph StateGraph for course gen | `app/services/ai/langgraph/course_generation_graph.py` (NEW) | 2 weeks | Phase 1 |
| 2.2 PostgreSQL checkpointing for LangGraph | `app/services/ai/langgraph/checkpointer.py` (NEW) | 3 days | 2.1 |
| 2.3 HITL via LangGraph interrupt() | `app/services/ai/langgraph/course_generation_graph.py` (add interrupt nodes) | 1 week | 2.1 |
| 2.4 AGT-03 Planner Agent | `app/services/ai/agents/planner_agent.py` (NEW) | 1 week | 2.1 |
| 2.5 AGT-06 Template Selector Agent | `app/services/ai/agents/template_selector_agent.py` (NEW) | 1 week | 2.1 |
| 2.6 Hybrid Supervisor (deterministic + LLM) | `app/services/ai/langgraph/supervisor.py` (NEW) | 1 week | 2.1 |
| 2.7 Real SSE streaming (G-11) | `app/services/ai/chat_orchestrator.py` (add process_message_stream), `app/routers/ai_chat.py` | 2 days | — |
| 2.8 Unified SemanticIndex (templates + components + APIs) | `app/services/ai/semantic_index.py` (NEW) | 1 week | Phase 0 |
| 2.9 Keep WorkflowOrchestrator as fallback | `app/services/workflow/orchestrator.py` (add degrade_to_sequential) | 1 day | 2.1 |

**Phase 2 Deliverable:** Multi-agent course generation via LangGraph. HITL via interrupt. Better content quality from specialised agents.

### Phase 3: Scale (Week 16-22) — OPERATIONAL MATURITY

| Task | File(s) | Effort | Depends On |
|------|---------|--------|------------|
| 3.1 MCP: content-writer-mcp | `app/mcp/content_writer/` (NEW package) | 2 weeks | Phase 2 |
| 3.2 MCP: safety-scan-mcp | `app/mcp/safety_scan/` (NEW package) | 1 week | Phase 2 |
| 3.3 MCP: template-registry-mcp | `app/mcp/template_registry/` (NEW package) | 1 week | Phase 2 |
| 3.4 Langfuse integration | `app/services/ai/langfuse_integration.py` (NEW) | 1 week | Phase 0 |
| 3.5 Grafana dashboards | `deploy/grafana/dashboards/` (NEW JSON) | 1 week | Phase 0 |
| 3.6 NeMo Guardrails (second-line safety) | `app/services/ai/nemo_guard.py` (NEW) | 1 week | 3.2 |
| 3.7 Accessibility validation (WCAG 2.1) | `app/services/ai/accessibility_validator.py` (NEW) | 3 days | — |
| 3.8 Enhanced SCORM validation (XSD) | `app/services/workflow/steps/scorm_export.py` (enhance) | 2 days | — |

**Phase 3 Deliverable:** Independently scalable generation. ML-based safety. Full observability stack.

---

## PART 12: WHAT TO KEEP UNCHANGED

These components are **better than their target equivalents** and should NOT be modified:

| Component | File | Why Keep |
|-----------|------|----------|
| ChatOrchestrator | `chat_orchestrator.py` | Chat is inherently linear. Battle-tested (834 tests). Keep for interactive chat. |
| JSONRepair | `json_repair.py` | 12-strategy pipeline is production-grade. No equivalent in target. Integrate into AGT-07. |
| SimilarCourseService | `similar_course_service.py` | 3-tier fallback is excellent. Extend scope, don't replace. |
| Propose-Before-Apply | `proposal_service.py`, `confirmation_token_service.py` | Stronger than anything in target. Keep as the mutation protocol. |
| CostTracker | `cost_tracker.py` | Functional and integrated. Add OTel/Langfuse export, don't replace. |
| WorkflowOrchestrator | `workflow/orchestrator.py` | Keep as fallback when LangGraph is unavailable. |
| CourseAssembler | `course_assembler.py` | Atomic create + audit + outbox is correct. Keep as AGT-09 equivalent. |
| SafetyService | `safety_service.py` | Keep as first-line defence (fast, regex). Add NeMo as second line. |
| IdempotencyService | `idempotency_service.py` | Exactly-once semantics. Production-grade. No changes needed. |
| OutboxService | `outbox_service.py` | Transactional outbox pattern. Industry standard. No changes needed. |

---

## PART 13: RISK REGISTER

| Risk | Mitigation |
|------|-----------|
| LangGraph API instability (v0.x) | Pin version. Abstract behind internal interface. Keep WorkflowOrchestrator as fallback. |
| Parallel generation hits LLM rate limits | Rate-limit-aware semaphore (max 3 concurrent). Per-page retry with exponential backoff. |
| MCP extraction increases latency | Benchmark before/after. Set latency budget (max 2× current). Keep in-process fallback. |
| Multi-agent prompts produce worse quality | A/B test single vs multi-agent output before full migration. |
| OTel migration breaks existing traces | Run both systems in parallel for 2 weeks. Validate equivalence. |
| Redis becomes SPOF for fan-out | Redis already in stack. Add Sentinel for production. Degrade to sequential on failure. |

---

## PART 14: SUCCESS CRITERIA

| Metric | Current | Target |
|--------|---------|--------|
| 30-page course generation time | 8-15 minutes | <2 minutes |
| Parallel page generation | Not possible | N pages concurrently (N = worker count) |
| HITL mechanism | Polling (5-30s latency) | Push-based (<1s notification) |
| Trace coverage (DB operations) | 0% | 100% (all 4 RAG tiers traced) |
| Trace standard | Proprietary (X-Trace-ID) | W3C Trace Context (OpenTelemetry) |
| Rate limiting survival | Resets on restart | Survives restarts (Redis-backed) |
| File storage durability | Lost on redeploy | Survives redeploys (S3/MinIO) |
| Safety detection | Regex-only (~80% catch) | Regex + NeMo (~95% catch) |
| Agent separation | 1 agent does everything | 3 specialist agents + deterministic services |
| MCP servers | 0 | 3 (content-writer, safety-scan, template-registry) |
| Tests passing | 834/834 | 834 existing + new agent/stream/MCP tests |
| Cost per course generation | $0 (mock) | ~$0.02-0.10 (LLM, 10-30 pages) |

---

## BUILD INSTRUCTIONS

1. **Read the entire prompt before starting.** Understand the architecture before writing code.
2. **Work in phases.** Complete Phase 0 before Phase 1. Each phase is independently valuable.
3. **Run tests after every file change.** `PYTHONPATH=. python tests/run_<name>.py`
4. **Commit after each completed task.** Clear commit messages referencing gap IDs.
5. **Keep the existing 834 tests passing.** If a change breaks tests, fix the tests or reconsider the change.
6. **Use the existing patterns.** Follow the codebase conventions: stateless services, DB-first state, propose-before-apply.
7. **Graceful degradation everywhere.** Every new component must have a fallback path.
8. **The `ChatOrchestrator` is sacred.** Do not break the chat system. It works. It's tested. It stays.
9. **Do not build the deferred components** (A2A, K8s, all 9 agents, all 9 MCP servers, LangGraph for chat).
10. **When in doubt, keep it simple.** A service class is better than an over-engineered agent.

---

## PROMPT END
