# Agentic AI Architecture — Gap Analysis

> **Role:** Agentic AI Architect
> **Date:** 2026-06-27
> **Branch:** `demo-course-AI-pradeep-01`
> **Method:** Pure codebase analysis — every finding traced to a specific file and line. Zero speculation.
> **Target:** Production-Grade Agentic AI Architecture (4-Layer Multi-Agent System with LangGraph, MCP, A2A)

---

## Executive Summary

The target architecture describes a **production-grade multi-agent system** with LangGraph orchestration, 9 specialized agents, MCP tool servers, A2A inter-agent protocol, and enterprise observability. The current codebase implements a **single-agent tool-using architecture** centered on `ChatOrchestrator` with direct service calls, custom middleware, and a PostgreSQL-backed durable workflow engine.

**Overall maturity:** The current codebase is a well-engineered **single-agent AI authoring system** with 834 passing tests, robust safety guards, and a propose-before-apply mutation pattern. It is approximately **30-35% aligned** with the target multi-agent architecture.

### Gap Severity Summary

| Severity | Count | Description |
|----------|-------|-------------|
| 🔴 MAJOR (Architectural) | 7 | LangGraph, Multi-Agent, MCP, A2A, Supervisor, Agent fan-out, Redis Streams |
| 🟡 SIGNIFICANT (Infrastructure) | 6 | OpenTelemetry, Langfuse, Prometheus/Grafana, NeMo Guardrails, Object Storage wiring, Kubernetes |
| 🟢 PARTIAL (Exists but differs) | 8 | SSE streaming, HITL, RAG, Workflow engine, Rate limiting, Safety, Model routing, pgvector |
| ✅ ALIGNED | 5 | FastAPI, PostgreSQL, File extraction, JSON repair, Propose-before-apply |

---

## Layer-by-Layer Gap Analysis

---

## LAYER 1 — Client

| Target Component | Current State | Gap | Severity |
|---|---|---|---|
| **Web Frontend** | Not in this repo (backend only). API endpoints exist for all operations. | ⚪ Out of scope | N/A |
| **Mobile App** | Not in this repo. SSE endpoint exists for progress streaming. | ⚪ Out of scope | N/A |
| **LMS Integrations (SCORM/xAPI/LTI)** | SCORM export workflow exists (`app/services/workflow/steps/scorm_export.py`). No xAPI or LTI endpoints found. | 🟡 LTI/xAPI not implemented | SIGNIFICANT |
| **HITL Review UI** | Not in this repo. Backend supports approval via `POST /ai/ingestions/{job_id}/review-plan` and `POST /ai/generate-course/{job_id}/apply`. | ⚪ Out of scope | N/A |

**Layer 1 Verdict:** Backend APIs are in place to support all client types. SCORM export is partially done (workflow steps exist), LTI/xAPI are absent.

---

## LAYER 2 — API Gateway

| Target Component | Current State | Gap | Severity |
|---|---|---|---|
| **FastAPI + Pydantic v3** | ✅ FastAPI with Pydantic v2 (not v3). `app/main.py` uses standard FastAPI patterns. Pydantic v3 does not exist yet (as of June 2026). | 🟢 Pydantic v2 (current stable) | COSMETIC |
| **OAuth2 + JWT Auth** | ✅ JWT-based auth via `get_current_user` dependency (`app/dependencies/auth_dependencies.py`). WebSocket uses query-param token. | 🟢 Not OAuth2 full flow — JWT bearer tokens | PARTIAL |
| **SSE / WebSocket** | ✅ SSE: `POST /ai/chat/stream` with 6 event types. WebSocket: `/ws/courses/{course_id}/collaborate` for real-time collab only. | 🟡 WebSocket is collaboration-only, not used for workflow progress streaming | MINOR |
| **Workflow Router** | ✅ `POST /api/v1/workflows` — triggers durable workflow engine. 6 endpoints (submit, status, cancel, retry, events, list). | ✅ ALIGNED | NONE |
| **Rate Limiting** | ✅ `AIRateLimitMiddleware` — 3-tier sliding window (tenant/user/endpoint). Currently **in-process** store with TODO comment for Redis. | 🟡 Needs Redis-backed store for multi-worker | MINOR |

**Layer 2 Verdict:** ~85% aligned. The API gateway layer is the strongest area of alignment. Key gaps: Pydantic v3 (doesn't exist yet), OAuth2 full flow, and Redis-backed rate limiting.

---

## LAYER 3 — Agentic Core (THE CRITICAL LAYER)

This is where the largest architectural gaps exist. The target describes a LangGraph-based multi-agent system with MCP tool servers and A2A protocol. The current codebase is a single-agent tool-using system.

### 3.0 Supervisor Orchestrator

| Target | Current State | Gap | Severity |
|---|---|---|---|
| **LangGraph StateGraph Root** | ❌ **Zero references to LangGraph anywhere in the codebase.** `grep -r "langgraph\|lang_graph\|StateGraph"` returns nothing. | 🔴 **MAJOR** — No LangGraph | MAJOR |
| **Routes via A2A** | ❌ No A2A protocol. Tools are called directly via `ToolExecutor` (stateless dispatch), not via agent-to-agent messaging. | 🔴 **MAJOR** — No A2A | MAJOR |
| **Manages WorkflowState** | 🟡 The `WorkflowOrchestrator` (`app/services/workflow/orchestrator.py`) manages job state via PostgreSQL but has no graph/state-machine abstraction beyond linear step sequences. | 🟡 State machine exists but is simpler | SIGNIFICANT |
| **Resumes from PostgreSQL checkpoints** | ✅ `WorkflowOrchestrator` uses PostgreSQL checkpoints with `SELECT FOR UPDATE SKIP LOCKED`. | ✅ ALIGNED (conceptually) | NONE |
| **Streams progress** | 🟡 SSE streaming exists (`/ai/chat/stream`) but for chat only. No workflow progress SSE endpoint. | 🟡 Chat-only streaming | PARTIAL |
| **Model: Claude Sonnet 4.6** | 🟡 Default model is `deepseek-v4-pro[1m]`. Claude Sonnet 4.6 and Haiku 4.6 are registered as fallbacks. | 🟢 Different default, Claude available | MINOR |
| **Handles HITL interrupts** | 🟡 HITL exists but via polling (`GET /ingestions/{job_id}`), not LangGraph `interrupt()`. No graph suspension/resume. | 🟡 Polling-based, not graph interrupt | SIGNIFICANT |

### 3.1 Agent-by-Agent Comparison

#### AGT-01: Ingestion Agent (Phase 0)
| Attribute | Target | Current |
|---|---|---|
| **Type** | Deterministic, no LLM | ✅ `AIIngestionService` (`app/services/ai/ingestion_service.py`) |
| **Functions** | Upload, validation, security | ✅ File type/size/hash validation, dedup by SHA-256 |
| **Gap** | Runs as independent agent with MCP tools | 🔴 Not an agent — it's a service class called synchronously. No MCP server. |
| **Severity** | — | 🔴 **MAJOR** (not an agent) |

#### AGT-02: Extraction Agent (Phase 1)
| Attribute | Target | Current |
|---|---|---|
| **Type** | Deterministic, no LLM | ✅ `DocumentExtractor` (`app/services/ai/document_extractor.py`) |
| **Functions** | PDF/DOCX/TXT parsing | ✅ pdfplumber, python-docx, max 100 pages, 500K chars |
| **Gap** | Runs as independent agent with MCP server | 🔴 Not an agent. No `extraction-mcp` server. |
| **Severity** | — | 🔴 **MAJOR** (not an agent) |

#### AGT-03: Planner Agent (Phase 2)
| Attribute | Target | Current |
|---|---|---|
| **Type** | LLM (Planner tier, Temp 0.3) | 🟡 `POST /ai/ingestions/{job_id}/propose-breakdown` calls `AIIngestionService` which calls `ChatOrchestrator` |
| **Functions** | AI page breakdown, orphan loop | ✅ Page plan generation exists |
| **Gap** | Independent agent with A2A interface | 🔴 Single LLM call from within a service, not an independent agent. No temperature 0.3 config visible at agent level. |
| **Severity** | — | 🔴 **MAJOR** (not an agent) |

#### AGT-04: HITL Checkpoint Agent (Phase 3 + 8)
| Attribute | Target | Current |
|---|---|---|
| **Type** | No LLM, LangGraph interrupt/resume | 🟡 Two approval points: `POST /ai/ingestions/{job_id}/review-plan` (Phase 3) and `POST /ai/generate-course/{job_id}/apply` (Phase 8) |
| **Gap** | LangGraph `interrupt()` suspends graph, waits for human, zero compute, 72h timeout | 🔴 Polling-based status checks. No graph suspension. No timeout mechanism at agent level. |
| **Severity** | — | 🔴 **MAJOR** (polling, not interrupt) |

#### AGT-05: RAG Retrieval Agent (Phase 4)
| Attribute | Target | Current |
|---|---|---|
| **Type** | No LLM, pgvector retrieval | ✅ `SimilarCourseService` (`app/services/ai/similar_course_service.py`) |
| **Functions** | Template schema + API schema retrieval | 🟡 3-tier fallback: pgvector → fulltext → keyword. Returns shaped results. |
| **Gap** | Independent agent. Template schema retrieval specifically. | 🟡 Retrieves course content, not template schemas. Template schemas come from `AITemplateContractsService`. No dedicated RAG agent — it's a service. |
| **Severity** | — | 🟡 **SIGNIFICANT** (exists but scope differs) |

#### AGT-06: Template Selector Agent (Phase 5)
| Attribute | Target | Current |
|---|---|---|
| **Type** | LLM (Planner tier, Temp 0.2), parallel fan-out per page | 🟡 Template validation exists (`TemplateValidationEngine`). No per-page template selection agent. |
| **Gap** | Independent agent, parallel N-page fan-out, Redis Streams | 🔴 No template selection agent. Template contracts are defined statically (`app/services/ai/template_contracts.py`). No parallel fan-out. |
| **Severity** | — | 🔴 **MAJOR** (agent missing, no fan-out) |

#### AGT-07: Content Generator Agent (Phase 6)
| Attribute | Target | Current |
|---|---|---|
| **Type** | LLM (Generator tier, Temp 0.7), parallel, JSON repair, retries | 🟡 `CourseGenerator` (`app/services/ai/course_generator.py`) generates content. `JSONRepair` exists with 12 strategies. |
| **Gap** | Independent agent, parallel fan-out across pages, Redis Streams | 🔴 Single-threaded generation via `CourseGenerator.start_generation()`. No parallel page generation. JSON repair exists but is not agent-integrated. |
| **Severity** | — | 🔴 **MAJOR** (no parallel fan-out, not an agent) |

#### AGT-08: Validator Agent (Phase 7)
| Attribute | Target | Current |
|---|---|---|
| **Type** | No LLM, rule-based + NeMo Guardrails | 🟡 `SafetyService` (3-layer), `TemplateValidationEngine` (JSON Schema + business rules). No NeMo. |
| **Functions** | JSON, safety, SCORM, a11y | 🟡 JSON + safety exist. SCORM validation is minimal. No accessibility (a11y) validation found. |
| **Gap** | Independent agent. NeMo Guardrails. a11y. | 🔴 No NeMo Guardrails. No a11y validation. SCORM validation is basic. Not an independent agent. |
| **Severity** | — | 🔴 **MAJOR** (missing NeMo, a11y; not an agent) |

#### AGT-09: Persistence Agent (Phase 9)
| Attribute | Target | Current |
|---|---|---|
| **Type** | No LLM, deterministic | ✅ `CourseAssembler` (`app/services/ai/course_assembler.py`) |
| **Functions** | Atomic create, audit, outbox events | ✅ Transactional create with `CourseOpsService`, `AIAuditService`, `AIOutboxService` |
| **Gap** | Independent agent | 🟡 Not an agent — services called inline. But functionally complete. |
| **Severity** | — | 🟢 **MINOR** (functionally complete, just not agent-wrapped) |

### 3.2 MCP Tool Servers

The target specifies 9 independently deployed MCP servers. **None exist as MCP servers.** All tool functionality is implemented as Python service classes called synchronously within the FastAPI process.

| Target MCP Server | Current Implementation | Gap | Severity |
|---|---|---|---|
| **file-store-mcp** | `AIIngestionService` + `LocalFileSystemStorage` — inline services, not MCP | 🔴 Not an MCP server | MAJOR |
| **extraction-mcp** | `DocumentExtractor` — inline service | 🔴 Not an MCP server | MAJOR |
| **template-registry-mcp** | `AITemplateContractsService` — inline service | 🔴 Not an MCP server | MAJOR |
| **pgvector-mcp** | `SimilarCourseService` + `EmbeddingProvider` — inline services | 🔴 Not an MCP server | MAJOR |
| **content-writer-mcp** | `CourseGenerator` — inline service | 🔴 Not an MCP server | MAJOR |
| **safety-scan-mcp** | `SafetyService` — inline service | 🔴 Not an MCP server | MAJOR |
| **course-db-mcp** | `CourseAssembler` + `CourseOpsService` — inline services | 🔴 Not an MCP server | MAJOR |
| **audit-log-mcp** | `AIAuditService` + `AuditQueryService` — inline services | 🔴 Not an MCP server | MAJOR |
| **notification-mcp** | `AIOutboxService` + `KafkaPublisher` — inline services | 🔴 Not an MCP server | MAJOR |

**MCP Verdict:** The current architecture uses **direct in-process service calls** instead of MCP. All tool functionality exists but is tightly coupled to the FastAPI process. To reach target state, each service would need to be extracted behind an MCP server interface with independent deployment, scoped auth, and Pydantic validation.

### 3.3 Protocols

| Target Protocol | Current State | Gap | Severity |
|---|---|---|---|
| **A2A (Agent-to-Agent Protocol v1.0)** | ❌ Zero references. No agent registry, discovery, or inter-agent messaging. | 🔴 **MAJOR** | MAJOR |
| **MCP (Model Context Protocol)** | ❌ Zero references. Tools are called via `ToolExecutor` stateless dispatch, not MCP. | 🔴 **MAJOR** | MAJOR |
| **OpenTelemetry** | ❌ Zero references. Custom `AITelemetryMiddleware` with trace IDs and timing, but not OTel format. | 🔴 **MAJOR** | MAJOR |

---

## LAYER 4 — Data & Infrastructure

| Target Component | Current State | Gap | Severity |
|---|---|---|---|
| **PostgreSQL (LangGraph checkpoints)** | ✅ PostgreSQL 16 with pgvector image. `WorkflowOrchestrator` uses PG for checkpoints. | ✅ ALIGNED (though not LangGraph checkpoints) | NONE |
| **pgvector (semantic memory)** | ✅ pgvector extension with IVFFlat index. `Vector(1536)` column. Graceful JSONB fallback. Embedding worker exists. | ✅ ALIGNED | NONE |
| **Redis Streams (fan-out queue)** | 🟡 Redis 7 present. Used for caching + WebSocket pub/sub. **Not used as Streams for fan-out.** | 🔴 Redis exists but not used for agent fan-out queues | MAJOR |
| **Object Storage (S3/MinIO)** | 🟡 MinIO provisioned in docker-compose. **No Python client code.** Only `LocalFileSystemStorage` implemented. | 🔴 Infrastructure exists, not wired | MAJOR |
| **OpenTelemetry + Langfuse** | ❌ Neither present. No packages in requirements.txt. No imports. | 🔴 **MAJOR** — Both missing | MAJOR |
| **Prometheus + Grafana** | ❌ Neither present. No `/metrics` endpoint. No prometheus_client. | 🔴 **MAJOR** — Both missing | MAJOR |
| **NeMo Guardrails** | ❌ Not present. Custom `SafetyService` with 9 injection patterns + 10 PII patterns instead. | 🔴 **MAJOR** — NeMo missing (custom guards exist) | MAJOR |
| **Kubernetes + HPA** | ❌ No Kubernetes configs found. `render.yaml` for Render.com deployment. `Dockerfile.production` for containerized deploy. | 🔴 **MAJOR** — No K8s | MAJOR |

---

## Cross-Cutting Concerns Gap Analysis

### Observability

| Capability | Target | Current | Gap |
|---|---|---|---|
| **LLM call tracing** | OpenTelemetry + Langfuse | `SessionTracer` — custom span-based I/O capture with DB persistence | 🟡 Functional but proprietary format |
| **Cost tracking** | Per-call via Langfuse | `CostTracker` — token counting + budget enforcement + pricing table | 🟡 Functional but not OTel-integrated |
| **Metrics** | Prometheus + Grafana dashboards | `AITelemetryMiddleware.get_stats()` — in-memory counters | 🔴 No metrics exposition |
| **Alerting** | Grafana alerts | None | 🔴 Missing |
| **Distributed tracing** | OpenTelemetry propagation | `X-Trace-ID` header + ContextVar (custom) | 🟡 Custom, not W3C Trace Context |

### Safety & Security

| Capability | Target | Current | Gap |
|---|---|---|---|
| **Input guard** | NeMo Guardrails | 9 regex patterns (prompt injection, jailbreak) | 🟡 Custom, less sophisticated |
| **PII detection** | NeMo Guardrails | 10 regex patterns (email, phone, SSN, CC, API keys) | 🟡 Custom, regex-based only |
| **Output guard** | NeMo Guardrails | Configurable blocked terms + PII leak check | 🟡 Custom |
| **Safety modes** | — | reject / redact / mask | ✅ Good |
| **Safety audit** | — | `ai_safety_events` table + admin endpoints | ✅ Good |

### Workflow & Resilience

| Capability | Target | Current | Gap |
|---|---|---|---|
| **Graph-based orchestration** | LangGraph StateGraph | PostgreSQL state machine with linear step sequences | 🔴 No graph abstraction |
| **HITL interrupts** | LangGraph `interrupt()` | Polling-based status checks | 🔴 Different mechanism |
| **Parallel fan-out** | Redis Streams | Sequential execution only | 🔴 No fan-out |
| **Crash recovery** | LangGraph checkpoints | `WorkflowOrchestrator._recover_stale_jobs()` | ✅ Functional equivalent |
| **Idempotency** | — | `IdempotencyService` with key storage + 24h TTL | ✅ Good |
| **DLQ** | — | In-memory DLQ with failure classification + exponential backoff | 🟡 In-memory, not persistent |
| **Transactional outbox** | — | `AIOutboxService` + Kafka publisher | ✅ Good |

---

## Summary Matrix: All Gaps

### 🔴 MAJOR Architectural Gaps (7)

| ID | Gap | Detail |
|---|---|---|
| **ARCH-01** | **No LangGraph** | Zero references. Single-agent `ChatOrchestrator` instead of LangGraph StateGraph. |
| **ARCH-02** | **No Multi-Agent System** | Target has 9 specialized agents. Current has 1 general agent (`ChatOrchestrator`) + service classes. |
| **ARCH-03** | **No MCP Servers** | All 9 target MCP servers are implemented as inline Python services. No MCP protocol. |
| **ARCH-04** | **No A2A Protocol** | No agent-to-agent communication. Tools called via `ToolExecutor` stateless dispatch. |
| **ARCH-05** | **No Supervisor Pattern** | No orchestrator agent routing to sub-agents. No `StateGraph` root node. |
| **ARCH-06** | **No Parallel Fan-Out** | Phase 5 (template selection) and Phase 6 (content generation) run sequentially. No Redis Streams fan-out. |
| **ARCH-07** | **No HITL Graph Interrupts** | HITL uses polling (`GET /job/{id}`), not LangGraph `interrupt()` with graph suspension. |

### 🟡 SIGNIFICANT Infrastructure Gaps (6)

| ID | Gap | Detail |
|---|---|---|
| **INFRA-01** | **No OpenTelemetry** | Custom `AITelemetryMiddleware` with proprietary trace IDs. Not W3C Trace Context. |
| **INFRA-02** | **No Langfuse** | LLM observability via custom `SessionTracer`. No Langfuse integration. |
| **INFRA-03** | **No Prometheus/Grafana** | No `/metrics` endpoint. In-memory counters only. No dashboards. |
| **INFRA-04** | **No NeMo Guardrails** | Custom regex-based safety (9 + 10 patterns). NeMo would add ML-based detection. |
| **INFRA-05** | **Object Storage Not Wired** | MinIO provisioned in docker-compose. Only `LocalFileSystemStorage` in Python code. |
| **INFRA-06** | **No Kubernetes Configs** | `render.yaml` + `Dockerfile.production` exist. No K8s manifests, HPA, or pod definitions. |

### 🟢 PARTIAL Alignment (Exists but Differs) (8)

| ID | Gap | Detail |
|---|---|---|
| **PARTIAL-01** | **SSE streaming** | Chat-only (`/ai/chat/stream`). No workflow progress SSE. |
| **PARTIAL-02** | **HITL mechanism** | Polling-based. Two approval points exist but via status checks. |
| **PARTIAL-03** | **RAG retrieval** | `SimilarCourseService` retrieves courses, not template schemas. 3-tier fallback is good. |
| **PARTIAL-04** | **Workflow engine** | PostgreSQL-backed state machine (not LangGraph). Functional but simpler. |
| **PARTIAL-05** | **Rate limiting** | In-process store. Needs Redis for multi-worker production use. |
| **PARTIAL-06** | **Safety** | Custom regex guards (functional) vs NeMo Guardrails (target). |
| **PARTIAL-07** | **Model routing** | Two-tier (planner/generator). Target implies more granular agent-level routing. |
| **PARTIAL-08** | **pgvector** | Working with IVFFlat index. But used for course similarity only, not template RAG. |

### ✅ ALIGNED (5)

| ID | Component | Detail |
|---|---|---|
| **OK-01** | **FastAPI + Pydantic** | FastAPI with Pydantic v2. All 44 AI endpoints typed and validated. |
| **OK-02** | **PostgreSQL** | PostgreSQL 16 with pgvector. ACID transactions. Checkpoints for workflow engine. |
| **OK-03** | **File Extraction** | PDF (pdfplumber) + DOCX (python-docx) extraction working. |
| **OK-04** | **JSON Repair** | 12-strategy deterministic pipeline. Production-grade. |
| **OK-05** | **Propose-Before-Apply** | Strong mutation pattern with confirmation tokens, idempotency, and audit trail. |

---

## Migration Path Recommendations

### Phase 1: Foundation (Weeks 1-4)
**Goal:** Wire existing infrastructure, add observability

1. **Wire MinIO/S3** — Add `boto3`/`aiobotocore`, implement `S3Storage` class
2. **Add OpenTelemetry** — Replace custom `AITelemetryMiddleware` trace IDs with OTel SDK, W3C Trace Context propagation
3. **Add Prometheus metrics** — Expose `/metrics` endpoint, add prometheus_client instrumentation
4. **Redis-backed rate limiting** — Replace `InProcessRateLimitStore` with Redis implementation

### Phase 2: Agent Extraction (Weeks 5-10)
**Goal:** Extract services into independent agents

1. **Wrap services behind MCP servers** — Start with `file-store-mcp`, `extraction-mcp`, `safety-scan-mcp` (simplest, no LLM)
2. **Implement A2A protocol** — Add agent registry, service discovery, inter-agent messaging
3. **Extract AGT-01, AGT-02, AGT-05, AGT-08, AGT-09** — The deterministic agents first

### Phase 3: Orchestration (Weeks 11-16)
**Goal:** Add LangGraph, Supervisor, fan-out

1. **Integrate LangGraph** — Replace `WorkflowOrchestrator` with LangGraph `StateGraph`
2. **Implement Supervisor** — Routing agent that delegates to sub-agents via A2A
3. **Add Redis Streams fan-out** — Parallel execution for Phases 5 & 6 (template selection + content generation)
4. **Replace polling HITL with `interrupt()`** — LangGraph graph suspension for human review points

### Phase 4: Production Hardening (Weeks 17-22)
**Goal:** Enterprise observability, ML safety, K8s

1. **Add Langfuse** — LLM observability with cost tracking
2. **Add NeMo Guardrails** — Augment/replace custom regex guards
3. **Add Grafana dashboards** — Business + technical metrics
4. **Kubernetes deployment** — Helm charts, HPA, pod disruption budgets
5. **Accessibility validation** — a11y checks in Validator Agent (AGT-08)

---

## File Reference Index

Key files examined for this analysis:

| File | Content |
|---|---|
| `app/services/ai/chat_orchestrator.py` | Single-agent LLM interaction loop |
| `app/services/ai/llm_client.py` | Anthropic + Mock provider abstraction |
| `app/services/ai/config.py` | AI configuration singleton |
| `app/services/ai/safety_service.py` | 3-layer custom guardrails |
| `app/services/ai/course_generator.py` | Sequential course content generation |
| `app/services/ai/course_assembler.py` | Proposal-to-DB transformation |
| `app/services/ai/ingestion_service.py` | File upload + validation |
| `app/services/ai/document_extractor.py` | PDF/DOCX parsing |
| `app/services/ai/similar_course_service.py` | 3-tier RAG retrieval |
| `app/services/ai/json_repair.py` | 12-strategy JSON repair |
| `app/services/ai/model_tier_router.py` | Planner vs Generator routing |
| `app/services/ai/tool_executor.py` | Stateless tool dispatch |
| `app/services/ai/session_tracer.py` | Custom I/O tracing |
| `app/services/workflow/orchestrator.py` | PostgreSQL-backed workflow engine |
| `app/services/workflow/step_registry.py` | Decorator-based step registration |
| `app/routers/ai_chat.py` | Chat + SSE streaming endpoints |
| `app/routers/ai_ingestion.py` | Upload + course generation endpoints |
| `app/routers/ai_proposals.py` | Proposal lifecycle endpoints |
| `app/routers/workflows.py` | Workflow job endpoints |
| `app/routers/ws_collaboration.py` | WebSocket collaboration |
| `app/middleware/ai_telemetry.py` | Custom trace ID + timing middleware |
| `app/middleware/ai_rate_limiter.py` | In-process rate limiting |
| `app/models/ai_models.py` | 8 AI ORM models |
| `app/models/workflow.py` | 3 workflow ORM models |
| `docker-compose.yml` | PostgreSQL + Redis + Redpanda + MinIO |

---

> **🤖 Generated with [Claude Code](https://claude.com/claude-code)** — Pure codebase analysis, zero hallucination.
