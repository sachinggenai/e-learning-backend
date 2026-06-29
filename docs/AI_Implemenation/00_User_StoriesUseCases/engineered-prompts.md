# Engineered Prompts — MCP Architecture Implementation

> **Source:** `session-prompts-log.md` (62 prompts)  
> **Purpose:** Improved versions of each prompt for future re-use  
> **Date:** 2026-06-29

---

## P1: Session History

**Original:** Provide me the session history which is running previously which was closed recently

**Engineered:**
```
Locate the most recent Claude Code session transcript under
~/.claude/projects/C--Users-ADMIN-e-learning-backend/. Identify the
2 largest JSONL files by modification time. For the most recent one,
extract: session ID, date range, git branch, files modified, tasks
completed, and what was in-progress when the session closed. Summarize
in a table.
```

---

## P2: Continue Previous Work

**Original:** Pick up the LiteLLM setup where we left off

**Engineered:**
```
Continue from the previous session (4e57945e-afb6-4041-b193-014cc7a448a4).
Check current state: Ollama process status, model availability, venv
packages installed, .env configuration. Then resume from the incomplete
checklist item: install LiteLLM, create proxy config, test Anthropic
API translation. Report current state before making any changes.
```

---

## P3: Task Status Report

**Original:** List out the task which has completed and which has pending and why these tasks are necessary, create md file

**Engineered:**
```
List all active tasks with status (completed/pending). For each pending task,
explain: (a) what it depends on, (b) why it's necessary for the overall goal,
(c) what would break if skipped. Output as a markdown file in
docs/local_LLM_Setup/ with a status table + dependency graph in ASCII.
```

---

## P4: App Integration Test

**Original:** Continue with task 5 (app integration)

**Engineered:**
```
Task: Verify the FastAPI app routes LLM calls through the local proxy.
Steps:
1. Check Docker services (PostgreSQL, Redis) are running
2. Start FastAPI on port 8000 with ANTHROPIC_BASE_URL=http://localhost:4000
3. Test POST /api/v1/ai/chat with a real prompt
4. Confirm the full chain: app → Anthropic SDK → local_proxy → Ollama → response
5. Report latency, token usage, and any errors at each hop
```

---

## P5: Architecture Decision — Multi-LLM Strategy

**Original:** then instead of buliding adopter to convert local llm to anthropic or wise versa...

**Engineered:**
```
Role: Solution Architect evaluating multi-provider LLM strategies.

Context:
- llm_client.py is hardcoded to Anthropic SDK (LLMProvider.ANTHROPIC | MOCK)
- Adding Ollama required a fragile translation proxy (local_proxy.py)
- We need: Anthropic, OpenAI, Ollama, DeepSeek — all interchangeable

Constraints:
- Zero breaking changes to LLMClient public API
- Streaming + tool calling must work across all providers
- Local GPU: RTX 2060 (6GB VRAM), models ≤7B params
- 862 existing tests must continue passing

Deliverable:
Present 3 architecture options with a trade-off matrix:
- Effort (files changed, LOC)
- Risk (test breakage, regression surface)
- Maintainability (new provider add time)
- Provider coverage (how many backends supported)
Recommend one with justification citing existing codebase patterns.
```

---

## P6: MCP Architecture — TRD & Impact Analysis

**Original:** As Agentic AI Architect, I would like to find out impactected code(area)...

**Engineered:**
```
Role: Agentic AI Architect. Design an MCP (Model Context Protocol) based
architecture to make the AI subsystem LLM-provider-agnostic.

Research Scope (3 modules — explore each before designing):
1. app/services/ai/ — LLMClient, ChatOrchestrator, config, model_tier_router,
   all agents (planner, content_generator, template_selector)
2. app/mcp/ — existing MCP servers (content_writer:8001, safety_scan:8002,
   template_registry:8003) — understand their custom protocol
3. app/services/ai/course_generator.py + agents/ + langgraph/ — course
   generation pipeline, fanout pattern, LangGraph state machine

TRD Must Include:
1. Impacted files matrix (file | class | method | LOC changed)
2. Architecture diagram (ASCII) — app → MCP Gateway → backends
3. New class hierarchy: LLMBackend ABC, ProviderRegistry, MCPClientManager
4. Canonical message format spec (recommend OpenAI Chat as standard)
5. 5-phase migration plan with per-phase verification gates
6. 4-tier degradation strategy (Full MCP → Gateway Down → All Down → Mock Only)
7. Test protection plan (how 836 tests survive each phase)
8. Configuration changes (new env vars, deprecated vars)

Hard Constraints:
- Zero changes to router layer (ai_chat.py, ai_tools.py, etc.)
- Mock provider stays in-process (no MCP dependency in tests)
- Streaming + tool calling must work across ALL backends
- Dynamic provider registration at runtime
```

---

## P7: Phase 1 — Foundation

**Original:** Proceed (implement Phase 1)

**Engineered:**
```
Implement Phase 1 of the MCP Architecture plan — Foundation layer.
Zero impact on running app.

Deliverables:
1. app/services/ai/mcp_client/message.py — canonical ChatMessage,
   ChatCompletionRequest, ChatCompletionResponse (OpenAI format)
2. app/services/ai/mcp_client/types.py — DegradationTier, ProviderHealth,
   ProviderInfo
3. app/mcp/llm_gateway/backends/base.py — LLMBackend ABC with:
   - async chat(request) -> ChatCompletionResponse
   - async chat_stream(request) -> AsyncIterator[ChatCompletionStreamEvent]
   - health() -> ProviderHealth
4. app/mcp/llm_gateway/backends/mock_backend.py — deterministic mock
5. app/mcp/llm_gateway/backends/anthropic_backend.py — Anthropic SDK wrapper
6. app/mcp/llm_gateway/provider_registry.py — thread-safe register/unregister/
   resolve with model-to-backend index
7. app/mcp/llm_gateway/server.py — standalone FastAPI on port 8004 exposing
   /health, /tools/list, /tools/call (chat_completion, stream_completion,
   list_providers)

Verification:
- Start Gateway: PYTHONPATH=. python app/mcp/llm_gateway/server.py
- curl /health → 200, providers listed
- curl /tools/call → valid chat_completion response from MockBackend
- curl /tools/call → valid response from AnthropicBackend
- Main app on :8000 continues running unchanged
```

---

## P8: Phase 2 — Integration

**Original:** Proceed to Phase 2

**Engineered:**
```
Implement Phase 2 — wire the main app to use MCP Gateway.

Deliverables:
1. app/services/ai/mcp_client/mcp_client_manager.py — singleton:
   - start() / stop() for FastAPI lifespan
   - Heartbeat loop (15s interval) with /health check
   - Degradation tier auto-detection
2. app/services/ai/mcp_client/llm_gateway_client.py — HTTP client:
   - chat(request) — non-streaming via Gateway /v1/chat/completions
   - chat_stream(request) — SSE streaming
   - list_providers() — discover registered backends
   - Graceful error: return error response instead of throwing
3. app/services/ai/mcp_client/domain_tool_client.py — MCP tool client
4. app/services/ai/mcp_client/degradation_manager.py — circuit breaker
5. app/services/ai/adapters/llm_client_adapter.py — LLMMessage ↔ canonical
6. Refactor llm_client.py:
   - Add _mcp_chat() and _mcp_stream() methods
   - _anthropic_chat: try MCP Gateway first, fall back to direct SDK
   - _mock_chat: stays completely unchanged (in-process)
7. app/main.py — MCPClientManager start/stop in lifespan

Critical Constraint: All 836 existing tests must pass unchanged.
Mock path stays in-process — no MCP infrastructure needed for tests.
```

---

## P9: Phase 3 — OllamaBackend

**Original:** Proceed to Phase 3 — add OllamaBackend to Gateway

**Engineered:**
```
Implement app/mcp/llm_gateway/backends/ollama_backend.py.

Requirements:
- Direct HTTP to Ollama /api/chat — NO proxy, NO SDK, just httpx
- Convert canonical ChatCompletionRequest → Ollama chat format
- Convert Ollama response → canonical ChatCompletionResponse
- Handle streaming: Ollama NDJSON → canonical ChatCompletionStreamEvent
- Handle tool calling: canonical tools[] → Ollama function calling format
- Auto-detect installed models via GET /api/tags on startup
- Map cloud model names → Ollama models (deepseek-v4-pro[1m] → qwen2.5:7b)

Registration:
- Add to Gateway server.py _init_registry()
- Add to backends/__init__.py exports
- ProviderRegistry: mark ollama as tier_affinity="both"

Verification:
- curl Gateway /v1/chat/completions with model=qwen2.5:7b → valid response
- curl with model=phi3:mini → valid response
- curl with stream=true → SSE events flow correctly
- Gateway /health shows ollama backend as healthy
```

---

## P10: Task 6 — Embeddings + Tool Calling

**Original:** Proceed with task 6, make sure you carefully perform code clean

**Engineered:**
```
Validate embeddings and tool calling end-to-end through the MCP Gateway.

Embeddings:
1. Test Ollama /api/embed with nomic-embed-text → confirm 768-dim vectors
2. Test Ollama /v1/embeddings (OpenAI-compatible endpoint)
3. Verify app's EmbeddingProvider chain: OpenAIBackend → Ollama

Tool Calling:
1. Send request with tools[] to MCP Gateway → OllamaBackend → qwen2.5:7b
2. Verify Ollama returns tool_calls[] with correct function name + arguments
3. Test through LLMClient: ToolDef → canonical → Gateway → Ollama → parsed back
4. Test multiple tools — verify model selects the correct one

Code Cleanup:
- Fix degradation tier logic (GATEWAY_DOWN when gateway healthy)
- Fix Gateway config defaults to include ollama
- Check all import paths, docstrings, error handling
```

---

## P11: Phase 4 — Domain Tools

**Original:** Proceed to Phase 4

**Engineered:**
```
Create Domain Tools MCP Server (port 8005) exposing the 7 ChatOrchestrator
tools as MCP endpoints. Wire ChatOrchestrator to use it with in-process
fallback.

Server (app/mcp/domain_tools/server.py):
- Standalone FastAPI using the same codebase + DB
- 7 MCP tools: list_pages, fetch_page, query_similar_courses,
  propose_create_page, propose_update_page, propose_delete_page,
  validate_course
- Each request creates a fresh AsyncSession from SessionLocal
- Wraps ToolExecutor, AIProposalService, UnifiedValidator

ChatOrchestrator Integration:
- Add _execute_tool_mcp_fallback() method
- Try DomainToolClient first → if unavailable → in-process ToolExecutor
- DegradationManager tracks domain tool circuit breaker

Verification:
1. Start server: PYTHONPATH=. uvicorn app.mcp.domain_tools.server:app --port 8005
2. curl /tools/list → 7 tools with JSON schemas
3. curl /tools/call validate_course → valid response
4. Kill server → verify in-process ToolExecutor fallback works
5. Session trace shows tool calls with latency breakdown
```

---

## P12: Deprecate Proxy + Test Sweep

**Original:** Deprecate local_proxy.py and run final test sweep

**Engineered:**
```
Step 1 — Deprecate local_proxy.py:
- Add DEPRECATED docstring at top: "Replaced by OllamaBackend in LLM Gateway"
- Kill process on port 4000
- Verify OllamaBackend handles all LLM calls without proxy

Step 2 — Test Sweep:
Run all 19 standalone test runners under tests/run_*.py.
For each suite, report: passed/failed count, any failures with stack trace.
For any failure NOT present before MCP changes, perform RCA before proceeding.

Success: All test suites pass identically to pre-MCP baseline (862/863).
```

---

## P13: Real LLM Validation — No Mock

**Original:** don't try to run any thing with mock we need use actual llm, mcp, RAG, AI Agent...

**Engineered:**
```
Validate the Postman collection (52 endpoints) against the live API using
ONLY real local LLM. No mock backend. No cloud API.

Pre-flight:
- Restart all services: Ollama (11434), LLM Gateway (8004), Domain Tools (8005), App (8000)
- Confirm Gateway /health shows ollama backend with qwen2.5:7b + phi3:mini
- Confirm App feature-status shows qwen2.5:7b as active model

Validation Rules (every endpoint):
1. LLM endpoints: Gateway log must show POST /v1/chat/completions 200 OK
2. RAG endpoints: response must show retrieval_tier_used = tier1 or tier2
3. Trace: session trace must show real model names, not "mock"
4. Token usage: must be >0 (or documented as cosmetic gap)

Failure Handling:
For ANY failure, document in TPO-Gap-Analysis-TRD.md Part E:
- Root cause chain (minimum 3 levels deep)
- Exact code location (file:line)
- Before/after evidence
- Fix approach with effort/risk rating

Success: 90%+ endpoints return 2xx with real LLM content visible in trace.
```

---

## P14: Fix RAG Embeddings

**Original:** Fix the RAG embeddings tier1 — point OpenAIBackend to Ollama

**Engineered:**
```
Fix: OpenAIBackend in embedding_provider.py ignores OPENAI_BASE_URL env var.

Root Cause: openai.AsyncOpenAI(api_key=...) created without base_url parameter.
SDK defaults to https://api.openai.com/v1 which times out (no valid key).

Changes:
1. Read OPENAI_BASE_URL in OpenAIBackend.__init__
2. Pass base_url to openai.AsyncOpenAI(base_url=...) when set
3. Auto-detect dimension: nomic-embed-text → 768, ada-002 → 1536
4. Add _MODEL_DIMENSIONS lookup dict for common models

Verification:
- curl Ollama /v1/embeddings → 768-dim vector returned
- RAG query via app: tier1 latency <500ms (was 4,608ms timeout)
- Session trace shows embedding_provider: OpenAIBackend
```

---

## P15: Update TRD

**Original:** Update the TRD with RAG tier1 fix

**Engineered:**
```
Update TPO-Gap-Analysis-TRD.md with RAG tier1 fix documentation:
- Section E.9: Root cause, code fix, before/after metrics
- Before: tier1 = 4,608ms timeout to OpenAI cloud
- After: tier1 = 351ms (cold) / ~100ms (warm) via local Ollama
- Files changed: embedding_provider.py OpenAIBackend class
- Update Pending Actions table: mark OpenAIBackend fix as COMPLETE
```

---

## P16: Update Start Scripts

**Original:** Update start-all.ps1 with MCP Gateway and Domain Tools

**Engineered:**
```
Update both start-all.ps1 and start-all.sh to include MCP Core Infrastructure.

Add to script vars:
- Gateway: port 8004, module app.mcp.llm_gateway.server:app
- Domain Tools: port 8005, module app.mcp.domain_tools.server:app

Add STEP 3a (after optional MCP servers, before FastAPI):
- Kill stale processes on 8004/8005
- Start Gateway via uvicorn in background
- Start Domain Tools via uvicorn in background
- Log PIDs for Ctrl+C cleanup

Update display: show Ollama status, MCP Architecture section with
Gateway + Domain Tools health URLs.

Both PS1 and SH versions must be updated identically.
```

---

## P17: Vector DB Seed Script

**Original:** now As RAG is returning empty, now try to understand...

**Engineered:**
```
Create scripts/seed_vectordb.py to populate pgvector course_embeddings.

Phase 1 — Audit:
1. Check all .mmd flow files under docs/AI_Implemenation/ for RAG query patterns
2. Query course_embeddings table: count rows, check vector dimension
3. Query courses table: count, list titles
4. Confirm embedding model compatibility: nomic-embed-text = 768-dim
5. If dimension mismatch: ALTER TABLE course_embeddings ALTER COLUMN
   embedding TYPE vector(768)

Phase 2 — Design:
- Data source: 5 sample courses with 3 pages each covering instructional
  design, e-learning, LMS, compliance, and accessibility topics
- Embedding model: nomic-embed-text via Ollama /api/embed (768-dim)
- Backup: export all course_embeddings to data/vectordb_backups/
  seed_backup_YYYYMMDD_HHMMSS.json (timestamped)
- Idempotency: compute content_hash, skip if unchanged

Phase 3 — Script Features:
- --backup-only: export and exit
- --restore FILE: import from backup JSON
- --force: skip confirmation prompt
- --skip-seed: don't insert sample courses (re-embed existing only)
- --skip-validate: don't run test queries after embedding

Phase 4 — Validation:
- 6 test queries with expected matches (e.g., "instructional design" →
  SEED-COURSE-001 with score >0.5)
- Run via POST /api/v1/ai/tools/query_similar_courses
- Session trace must show retrieval_tier_used: tier1

Success: tier1 returns results at 68ms warm latency with cosine similarity >0.5.
Script is re-runnable anytime — same hash = skip, new content = re-embed.
```

---

## P22: CSA Course Generation

**Original:** use SB2-Cybersecurity Awareness docx to generate course called 'csa'...

**Engineered:**
```
Generate a complete e-learning course from the cybersecurity awareness docx.

Input: c:/Users/ADMIN/Downloads/SB2-Cybersecurity Awareness for the Modern Workplace.docx (328KB)

Pipeline (7 steps — validate each with real AI, no mock):
1. POST /ai/sessions — create session for course "csa"
2. POST /ai/ingestions — upload docx (multipart, 328KB), extract sections
3. POST /ai/ingestions/{jid}/propose-breakdown — LLM-driven page plan
4. POST /ai/ingestions/{jid}/review-plan — approve plan
5. POST /ai/generate-course — generate content via ContentGeneratorAgent
   → qwen2.5:7b via MCP Gateway (use_llm=true, timeout=600s)
6. POST /ai/generate-course/{jid}/apply — persist to DB
7. POST /api/v1/export/scorm/{courseId} — export SCORM zip

Validation per step:
- Gateway logs: confirm POST /v1/chat/completions 200 OK for every LLM call
- Session trace: real model names, real token counts
- RAG: tier1 embeddings active during generation
- Content: fetch generated pages, verify real HTML (not lorem ipsum)
- Provenance: model field must report qwen2.5:7b, not mock
- Export: valid SCORM 1.2 manifest with all pages

Document: every step's input payload and output response for audit trail.
```

---

## P25: Fix Provenance Bug

**Original:** fix the provenance bug — model field should report ollama/qwen2.5:7b not mock

**Engineered:**
```
Bug: CourseGenerator.start_generation() always writes "model": "mock" in
provenance, even when real LLM is used via ContentGeneratorAgent.

Root cause: Hardcoded string at course_generator.py line 198:
  "provenance": {"model": "mock", ...}

Fix:
1. Add self._last_model_used and self._last_provider_used to __init__
   (default: "mock"/"mock")
2. In _generate_pages_with_llm: set from llm_client.model and
   llm_client.provider.value
3. In _generate_pages (mock fallback): set to "mock"/"mock"
4. In start_generation: use self._last_model_used instead of "mock"
5. Add "provider" field to provenance for clarity

Verification: After course generation, query ingestion job —
source_metadata.generated_course.provenance.model must be "qwen2.5:7b".
```

---

## P26: Assessment Template Gap — RCA

**Original:** why did the page breakdown missed assessment template and page, perform RCA...

**Engineered:**
```
RCA Request: The docx "SB2-Cybersecurity Awareness" contains assessment/
quiz content, but the page breakdown assigned all pages as content-text.
No final-assessment template was selected.

Investigation Path:
1. Check _suggest_template() keyword list — what words trigger final-assessment?
2. Check the extracted section content for the last section — does it contain
   any of those keywords?
3. Check if the LLM-driven breakdown (_llm_propose_breakdown) was called or
   if fallback to rule-based occurred
4. If rule-based: is the keyword list exhaustive enough?
5. If LLM: check raw LLM response — did it identify assessment content?

Deliverable: Root cause chain (section content → keyword match failure →
template assignment), with exact keywords checked and section text that
should have matched. Recommendation: LLM-driven classification replacing
keyword matching.
```

---

## P27: LLM-Driven Breakdown — Implementation

**Original:** implement option C, make sure you pass desire context...

**Engineered:**
```
Replace _suggest_template() keyword matching with _llm_propose_breakdown()
that uses phi3:mini to semantically classify each document section.

Function location: app/routers/ai_ingestion.py

Context to pass to LLM:
1. Full TEMPLATE_SCHEMAS from ContentGeneratorAgent (all 5 types,
   complete component JSON with data fields)
2. RAG context: top 3 similar courses by pgvector cosine similarity
   (embeddings via nomic-embed-text)
3. Section content previews: heading + first 500 chars
4. Section char_counts: to decide merge (<200 chars) or split (>5000 chars)

LLM Configuration:
- Model: phi3:mini via MCP Gateway (http://localhost:8004/v1/chat/completions)
- temperature: 0.3, max_tokens: 8192
- System: "You are an instructional design AI. Output only valid JSON."

Output Schema:
[{"title": "Descriptive Page Title", "template_type": "final-assessment",
  "rationale": "Why this template was chosen", "source_section_ids": [0,1],
  "order": 0}]

Fallback: If LLM unavailable or returns invalid JSON → _rule_based_breakdown()
with existing keyword matching.

JSON Repair: Handle truncated output (LLM may hit token limit mid-JSON) —
find last valid object, close array gracefully.

Field Normalization: Map LLM output keys → storage format:
title → proposed_title, template_type → suggested_template_type

Success: CSA docx generates at least 1 final-assessment page with
descriptive titles (not filename).
```

---

## P33: Deep RCA — Validator Failures

**Original:** Now act as AI Architect trage Chat... + Proposals... perfrom deep RCA...

**Engineered:**
```
Role: AI Architect performing Root Cause Analysis on 2 test failures.

Failure 1 — Token Usage {input: 0, output: 0}:
- Test: scripts/validate_api_flows.py, Flow 5 (Chat)
- Symptom: token_usage shows 0/0 despite valid LLM content returned
- Trace shows phi3:mini (PLANNER tier) was used
- Expected: input >0, output >0

Failure 2 — Cancel Proposal 403:
- Test: Flow 6 (Proposals), cancel step
- Symptom: PERMISSION_DENIED "Session doesn't own this proposal"
- Session and proposal created in same validator run

RCA Depth: Minimum 4 levels per failure:
1. Symptom (what the test sees)
2. Code path (exact file:line where failure occurs)
3. Root cause (why the code behaves this way)
4. Architectural gap (why wasn't this caught earlier)

Deliverable per failure:
- Root cause statement (1 sentence)
- 3 fix options with effort (LOC) and risk (regression surface) ratings
- Recommended approach with justification
```

---

## P34: Apply RCA Fixes

**Original:** apply the recommended fixes to the validator script

**Engineered:**
```
Apply fixes for both RCA findings to scripts/validate_api_flows.py:

Fix 1 — Token Usage:
- Relax check: accept token_usage = {0,0} when content is valid
- When tokens are 0, estimate from content length (chars/4)
- Print "estimated" label so it's clear tokens are approximate

Fix 2 — Cancel Proposal:
- Before cancel test: create a FRESH proposal in the CURRENT session
- Cancel the fresh proposal (guarantees same session ownership)
- Don't reuse proposals from previous validator runs

Plus API fix in app/routers/ai_proposals.py:
- CancelProposalRequest: add session_id field (was missing)
- cancel_proposal router: pass body.session_id instead of hardcoded ""

Success: scripts/validate_api_flows.py returns 39/39 passing.
```

---

## P41: Full CSA Pipeline with Real AI

**Original:** use SB2-Cybersecurity Awareness docx... create new cource called 'csa'... make sure its use MCPs(actual not mock)s, RAGs(actual not mock)s, LLMs(actual not mock), AI Agents(actual not mock)

**Engineered:**
```
End-to-end course generation from a real document using only real AI services.

Input: c:/Users/ADMIN/Downloads/SB2-Cybersecurity Awareness for the Modern Workplace.docx

Pipeline (every step uses real AI — verify via Gateway logs + session trace):
1. Create session for course "csa"
2. Upload 328KB docx → extract sections
3. LLM-driven breakdown (phi3:mini) → propose pages with template types
4. Review & approve plan
5. Generate course via ContentGeneratorAgent → qwen2.5:7b per page
6. Apply → persist pages + components to DB
7. Export → SCORM zip

Evidence Required Per Step:
- LLM: Gateway access log shows POST /v1/chat/completions 200 OK
- RAG: tier1 pgvector latency <500ms, real embedding model in trace
- AI Agents: ContentGeneratorAgent generation_metadata.method = "llm"
- MCP: Domain Tools called (check /tools/call in Domain Tools log)
- Provenance: model = qwen2.5:7b, provider = ollama

Deliverable: Document input/output for each step, session trace summary,
SCORM zip file, and highlight any gaps found.
```

---

## P44: Provenance Bug Fix

**Original:** fix the provenance bug — model field should report ollama/qwen2.5:7b not mock

**Engineered:**
```
Bug: CourseGenerator.start_generation() hardcodes provenance.model = "mock"
regardless of actual LLM usage.

Fix in app/services/ai/course_generator.py:
1. __init__: add self._last_model_used = "mock"
               self._last_provider_used = "mock"
2. _generate_pages_with_llm: after creating llm_client, set:
   self._last_model_used = llm_client.model
   self._last_provider_used = llm_client.provider.value
3. _generate_pages (mock path): set both to "mock"
4. start_generation: use self._last_model_used and self._last_provider_used
   instead of hardcoded "mock"

Verification: After generation, query job's source_metadata.generated_course
.provenance → model must be "qwen2.5:7b", provider "ollama".
```

---

## P46: Implement LLM-Driven Breakdown (Enhanced)

**Original:** implement option C make sure you pass desire context...

**Engineered:**
```
Replace the rule-based page breakdown with an LLM-driven one.

Function: _llm_propose_breakdown() in app/routers/ai_ingestion.py

LLM: phi3:mini via MCP Gateway direct HTTP call

Context passed to LLM:
1. Full TEMPLATE_SCHEMAS with component JSON (not just descriptions)
2. RAG context: top 3 similar courses from pgvector
3. Section headings + content previews + char_counts
4. Instructions for merging small sections, splitting large ones

Output: JSON array with title, template_type, rationale, source_section_ids

Fail-safe: If LLM unavailable or returns invalid JSON → _rule_based_breakdown()

JSON repair: Handle truncated output from token limit

Success criteria: CSA docx gets at least 1 final-assessment page with
descriptive title (not filename).
```

---

## P57: Vector DB Seed Script — Full Spec

**Original:** Now as RAG is returning empty... make a script to populate vector db...

**Engineered:**
```
Create scripts/seed_vectordb.py — production-grade vector DB seeding.

Features:
- First line: BACKUP existing course_embeddings to timestamped JSON
- --backup-only flag: export and exit
- --restore FILE flag: import from backup (disaster recovery)
- --force flag: skip confirmation prompt
- --skip-seed: don't insert courses (re-embed existing only)
- --skip-validate: don't run test queries

Seed Data: 5 courses × 3 pages each covering:
- Instructional Design (ADDIE, Bloom's Taxonomy, Assessment)
- E-Learning Development (Articulate Storyline)
- LMS Administration (Moodle, Canvas)
- Corporate Training & Compliance
- Accessible & Inclusive E-Learning (WCAG)

Embedding: nomic-embed-text (768-dim) via Ollama /api/embed
Dimension: Must match course_embeddings.embedding Vector column

Idempotency: content_hash check → skip if unchanged since last embed

Validation: 6 test queries with expected course matches at >0.5 cosine similarity

Success: Script runs cleanly, tier1 RAG returns results at 68ms warm latency.
Re-runnable: safe to execute multiple times, no duplicate data.
```
