# US-BKND-AI-034-PENDING — Durable Workflow Engine: RCA & Implementation Gap Analysis

**Story ID:** US-BKND-AI-034 / PEND-01
**Title:** Durable Workflow Engine for Long-Running AI Jobs
**Status:** ✅ SUPERSEDED — Engine implemented 2026-06-21 (commit 10b863a). 12 files, 3 tables, 6 endpoints, 146 tests.
**Priority:** 🔴 WAS must (now resolved)
**Estimate:** 3–5 days (actual implementation complete)
**RCA Date:** 2026-06-20
**Analysis Type:** Root Cause Analysis — why this story was marked COMPLETE before the engine existed

> **Superseded Note:** This document was written as pre-implementation RCA. The engine described as "missing" was implemented simultaneously with this document. The old `durable_workflow.py` (65-line stub) has been superseded by the new `app/services/workflow/` package. Retain for historical context.

---

## Executive Summary

Long-running AI jobs (>30s, e.g., 50-page course generation taking 5–15 minutes) run synchronously inside HTTP request-response cycles. They fail when gateways timeout at 30–60s, and all state is lost on process restart. The architecture flow (#3 v1.1) defines a 49-step flow but 5 steps in Phase 1 (Job Queue, Orchestrator Worker, Lock Manager, Checkpoint Loader) remain as infrastructure stubs. The only implementation is a 65-line in-memory `DurableWorkflow` class that **no production code imports**.

This document provides a detailed Root Cause Analysis of why PEND-01 was not implemented, what is missing in the related US-BKND-AI-015-IMP.md implementation playbook, and a trace through the codebase showing the full picture.

---

## 1. Problem Statement

| Attribute | Detail |
|-----------|--------|
| **What's broken** | Long-running AI operations (>30s) fail on HTTP timeout. Workflow state lost on restart. |
| **Current state** | `durable_workflow.py` (65 lines) — in-memory step advancement, zero DB persistence, zero consumers |
| **Required state** | PostgreSQL-backed state machine engine with background asyncio poll loop, distributed locking, checkpoint recovery, 6 REST endpoints, 3 DB tables |
| **Architecture flow gap** | Flow #3 v1.1: 5 of 49 steps stubbed — Phase 1 (Async Worker & Distributed State) entirely missing |
| **Spec available** | `US-AI-034_DURABLE_WORKFLOW_ENGINE.md` (2,299 lines) — complete blueprint with full Python code |

---

## 2. The Five Root Causes

### RC-1: INDEX.md Status Inflation — "COMPLETE" for an MVP Stub

**Evidence:**

| Source | What It Says | Reality |
|--------|-------------|---------|
| `INDEX.md:88` | `US-BKND-AI-034 \| Durable Workflow Engine for Long-Running AI Jobs \| ✅ COMPLETE \| COULD` | The "implementation" is a 65-line in-memory class with no DB persistence, no REST API, no background worker, and zero consuming code |
| `PENDING_TASKS_REPORT.md:33-46` | **❌ Missing** — "MVP: `durable_workflow.py` provides in-process checkpoint/retry" — 5 of 49 steps stubbed | The PENDING_TASKS_REPORT correctly identifies this as a production blocker |
| `VALIDATION_REPORT.md:58-59` | "✅ 100% Compliant — 44/49 steps implemented, 5 stubs for future infrastructure" | Counts 100% despite 5 production-critical infrastructure steps being missing |

**The decision chain:**
1. INDEX.md was compiled listing 47 stories. The 65-line `DurableWorkflow` + `AsyncPreviewJob` classes were written.
2. The test file `run_final_stories_tests.py` tested both classes with 9 basic assertions (step advancement, serialization, preview jobs).
3. Because a test existed and the module existed, INDEX.md marked the story "✅ COMPLETE."
4. **But 0 lines of production code import `durable_workflow.py`** — the entire module is dead code with no consumers.

**Why this matters:** Status inflation created a false sense of completion. No one was assigned to the 5 stubbed steps because the story was "done."

---

### RC-2: No Backend Enriched Story — Missing Acceptance Criteria

**Evidence:**

Glob search for `US-BKND-AI-034_enriched.md` → **no file exists on disk.**

Every other "COMPLETE" story has a backend enriched story file with:
- Implementation status
- Acceptance criteria
- What was done vs deferred
- Decision log
- Task breakdown

**Comparison with other stories:**

| Story | Enriched File | Lines | Implementation |
|-------|--------------|-------|----------------|
| US-BKND-AI-015 (RAG) | `US-BKND-AI-015_enriched.md` ✅ | ~800 | 1,500+ lines across 7 files |
| US-BKND-AI-015-IMP | `US-BKND-AI-015-IMP.md` ✅ | 2,992 | Complete implementation playbook |
| US-BKND-AI-033 (Outbox) | `US-BKND-AI-033_enriched.md` ✅ | ~600 | Event-driven outbox implemented |
| **US-BKND-AI-034** | **MISSING** ❌ | **0** | **65-line dead code** |
| US-BKND-AI-048 (DLQ) | Epic spec only | N/A | 281-line standalone `dead_letter_queue.py` |

The only spec for US-AI-034 is the **epic-level** `US-AI-034_DURABLE_WORKFLOW_ENGINE.md` (2,299 lines) — a detailed architecture document with full code, API contracts, and DB schemas — but **it has no implementation tracking**. It's a blueprint, not a status tracker.

**Why this matters:** Without an enriched story, there was no mechanism to:
- Define what "MVP" means (in-memory class vs PostgreSQL-backed orchestrator)
- Track which of the 10 task items were actually done vs deferred
- Document known gaps (the 5 stubbed architecture steps)
- Set acceptance criteria for production readiness

---

### RC-3: US-BKND-AI-015-IMP.md — Complete Blind Spot on Workflow Dependencies

**This is the critical finding.**

The 2,992-line US-BKND-AI-015-IMP.md is the **most thorough implementation playbook in the repository**. It guided the implementation of Advanced RAG (the most recent major feature, going from 25% → 100%). But searching the entire document reveals:

- **"034"** — 0 occurrences
- **"workflow"** — 0 occurrences
- **"durable_workflow"** — 0 occurrences
- **"orchestrator"** — 0 occurrences (except in context of `ChatOrchestrator`)
- **"job queue"** — 0 occurrences
- **"PEND-01"** — 0 occurrences
- **"background"** — appears only as "background re-indexing job (future iteration)" and "future background job" — always deferred, never integrated

**The word "job" appears 6 times in 2,992 lines**, all in these contexts:
- `"Create Job Record status=PROCESSING"` — architecture diagram reference
- `"background re-indexing job"` — deferred future work
- `"future background job"` — deferred future work
- `"import_job_id"` — schema field, not workflow-related
- `"import_job"` — checkpoint data key

**What US-BKND-AI-015-IMP.md SHOULD have covered:**

The similar course retrieval service (`SimilarCourseService.query_similar_courses()`) returns enriched results including excerpts, tone notes, and template breakdowns. These results feed into the chat orchestrator's system prompt, which then **generates course pages**. But:

1. **Page generation can take 5–15 minutes for a 50-page course** — well beyond HTTP timeout limits
2. The IMP file's "Architecture Integration Map" (§1.1) shows the data flow ending at the ChatOrchestrator — it never addresses what happens when the LLM takes minutes to generate pages
3. The orchestration flow (`_execute_mock_tool` → real service call) is synchronous — it blocks the HTTP request
4. Nowhere does the IMP file say: "For courses with >10 pages, dispatch to the workflow engine via `POST /api/v1/workflows`"

**The specific missing integration point:**

```
Phase 4 (Generation & Pruning) in the architecture flow:
  D5: "LLM Generator (Premium Model) — Schema-bound page generation"
  D6: "Atomic Checkpoint Write (CAS) — version++"
  
These assume a background worker with checkpoint persistence.
But the IMP file's implementation runs this synchronously in the HTTP handler.
```

**Why this matters:** The implementer of the most advanced feature (RAG) followed a 2,992-line playbook that never mentioned the infrastructure dependency they were implicitly depending on. The architecture flow diagram shows it, but the implementation playbook doesn't translate it into code requirements.

---

### RC-4: Priority Misclassification — "COULD" for a Production Blocker

**Evidence:**

| Source | Priority | Classification |
|--------|----------|---------------|
| `INDEX.md:88` | **COULD** | Optimization/backlog |
| `US-AI-034_DURABLE_WORKFLOW_ENGINE.md:4` | **MUST (MVP)** | The spec itself says MUST |
| `PENDING_TASKS_REPORT.md:43` | **🔴 MUST** | Production blocker |

The epic spec (`US-AI-034`) explicitly states **"Priority: MUST (MVP)"** on line 4. But INDEX.md reclassified it as **COULD**. This downgrade meant:
- Other higher-priority stories consumed available sprint capacity
- No sprint assigned it as blocking
- The 65-line MVP was deemed "good enough for COULD"

**Why this matters:** The epic author knew this was critical. The INDEX compiler downgraded it. The discrepancy was never caught because no backend enriched story forced a re-evaluation.

---

### RC-5: VALIDATION_REPORT "100% Compliant" Masked the Gap

**Evidence:**

`VALIDATION_REPORT.md:58-59`: "✅ 100% Compliant — 44/49 steps implemented, 5 stubs for future infrastructure"

This creates a perverse incentive:
- The report says 100% compliant
- No task is generated for the 5 stubs (they're "future infrastructure")
- The PENDING_TASKS_REPORT later identifies them as 🔴 MUST
- But by then, the "100%" label has already been communicated

The 5 stubbed steps represent the **entire background processing capability**:

| Stubbed Step | What It Does | Without It |
|-------------|-------------|-----------|
| B1: Job Queue | Accepts async jobs, returns 202 immediately | Client blocks until timeout |
| B2: AI Orchestrator Worker | Background asyncio loop processing jobs | All work synchronous in HTTP thread |
| B3: Redlock Lease Manager | `SELECT FOR UPDATE SKIP LOCKED` with heartbeat | No distributed concurrency; race conditions |
| B4: Checkpoint Loader | Resumes from last saved state after restart | Crash = all progress lost |

**Why this matters:** The validation methodology counted "implemented steps / total steps" but excluded infrastructure steps as "future" from the numerator. This created a 100% score that hid a production-critical gap.

---

## 3. Five Whys (Root Cause Chain)

```
Problem: Long-running AI jobs (>30s) fail on HTTP timeout. Workflow state lost on restart.

WHY?  → No durable workflow engine exists — only 65-line in-memory MVP.

WHY?  → US-BKND-AI-034 was marked COMPLETE after the MVP was written,
         and no further implementation was done.

WHY?  → INDEX.md classified it as COULD priority and marked it COMPLETE.
         No backend enriched story existed to define what COMPLETE actually means.
         No production code imports durable_workflow — it's dead code.

WHY?  → The implementation playbook (US-BKND-AI-015-IMP.md, 2992 lines)
         contains ZERO references to workflow, durable execution, or job
         queuing. It guided the developer through RAG implementation
         without mentioning that generated courses must run asynchronously.

WHY?  → The architecture flow chart shows the workflow engine phase (Phase 1)
         but the implementation playbook doesn't translate architecture
         requirements into code tasks. There's no "dependency checklist"
         linking architecture phases to implementation tasks.
```

---

## 4. What Was Actually Implemented vs Required

### 4.1 What Exists (the "COMPLETE" implementation)

**File:** `app/services/ai/durable_workflow.py` — 65 lines

| Class | What It Does | Production Readiness |
|-------|-------------|---------------------|
| `DurableWorkflow` | In-memory step advancement: `add_step()` → `advance()` → `fail_current()` → `to_dict()` | ❌ No DB persistence |
| `WorkflowState` enum | 5 states: PENDING, RUNNING, COMPLETED, FAILED, PAUSED | ❌ No PAUSED implementation |
| `AsyncPreviewJob` | In-memory async preview tracker: `mark_complete()` / `mark_failed()` | ❌ No background processing |

**Consumer:** Only `tests/run_final_stories_tests.py` (9 assertions). **Zero production imports.**

Verified via codebase grep:
```
$ grep -rn "from.*durable_workflow\|import.*DurableWorkflow" app/
  app/services/ai/durable_workflow.py:10:  class DurableWorkflow:
  app/services/ai/durable_workflow.py:43:  class AsyncPreviewJob:
  # NO OTHER IMPORTS — dead code

$ grep -rn "DurableWorkflow\|AsyncPreviewJob" app/
  app/services/ai/durable_workflow.py:10:  class DurableWorkflow:
  app/services/ai/durable_workflow.py:43:  class AsyncPreviewJob:
  # NO OTHER REFERENCES — dead code

$ grep -rn "from.*durable_workflow\|import.*DurableWorkflow" tests/
  tests/run_final_stories_tests.py:3:  from app.services.ai.durable_workflow import DurableWorkflow, WorkflowState, AsyncPreviewJob
  # Only the test file imports it
```

### 4.2 What's Required (the 2,299-line spec — `US-AI-034_DURABLE_WORKFLOW_ENGINE.md`)

| Layer | Files Needed | Status |
|-------|-------------|--------|
| ORM Models | `app/models/workflow.py` — 3 tables (`workflow_type_definitions`, `workflow_jobs`, `workflow_job_events`), 9 indexes | ❌ Not created |
| Repository | `app/repositories/workflow_repository.py` — 15+ methods including `try_lock_pending()`, `transition()`, `heartbeat()`, `find_stale_running_jobs()` | ❌ Not created |
| Orchestrator | `app/services/workflow/orchestrator.py` — background poll loop, state machine runner, crash recovery, webhook delivery, concurrency limiting | ❌ Not created |
| Step Registry | `app/services/workflow/step_registry.py` — decorator-based `register()/get()` pattern | ❌ Not created |
| Step Functions | `app/services/workflow/steps/course_generation.py` (4 states: validate_input, generate_pages, validate_course, create_batch_proposal) + `scorm_export.py` (5 states) | ❌ Not created |
| REST API | `app/routers/workflows.py` — 6 endpoints: POST submit, GET status, POST cancel, POST retry, GET events, GET list | ❌ Not created |
| Alembic Migration | Migration creating 3 tables with CHECK constraints, partial indexes, foreign keys | ❌ Not created |
| Feature Flag | `durable_workflow_engine` in `feature_flags.py` | ❌ Not added |
| App Wiring | `app/main.py` lifespan hooks for orchestrator start/stop, router registration | ❌ Not added |
| Tests | 6 test files: ORM (4 scenarios), Repository (15), Orchestrator (11), API (14), E2E (7), Export integration (2) = **53 scenarios** | ❌ Not created |

### 4.3 Adjacent Components Also Stubbed

The following components exist as standalone in-memory services with no integration into a durable workflow:

| Component | File | Lines | Status | Integration Gap |
|-----------|------|-------|--------|----------------|
| Dead Letter Queue | `app/services/ai/dead_letter_queue.py` | 281 | ✅ Implemented | No connection to workflow job failures — DLQ enqueues independently |
| Job Status Tracker | `app/services/ai/job_status_service.py` | 85 | ✅ Implemented | In-memory dict — replaced by `workflow_jobs` table |
| Course Ops Service | `app/services/ai/job_status_service.py` | 57-87 | ✅ Implemented | No async workflow dispatch for create/delete/archive |
| Policy Engine | `app/services/ai/policy_engine.py` | N/A | ✅ Implemented | No integration with workflow state machine transitions |
| Lock Manager | `app/services/ai/lock_manager.py` | N/A | ✅ Implemented | READ/WRITE locks only — no workflow job locking |

### 4.4 Job Classes Covered by This Story (from Spec §1.2)

| Job Type | Typical Duration | Current Fate |
|----------|-----------------|-------------|
| `course_generation` | 2–15 min | Runs synchronously → HTTP timeout at 30–60s |
| `batch_content_repair` | 30s–5 min | Not implemented at all |
| `scorm_export` | 10s–3 min | Runs synchronously (works for small courses, fails for large) |
| `ai_session_tool_batch` | 5s–1 min | Runs synchronously (usually works) |

---

## 5. Specific Missing Elements in US-BKND-AI-015-IMP.md

The Advanced RAG implementation playbook (US-BKND-AI-015-IMP.md) is the most meticulously detailed specification in the repository — 2,992 lines, 20 tasks, 15 files, 12 architecture decisions. It guided the developer from 25% → 100% RAG compliance. But it is completely silent on workflow dependencies.

### 5.1 What the IMP File Should Have Contained

**Missing Section: "Dependency: Workflow Engine for Generated Courses"**

The RAG retrieval returns similar course examples → the AI uses them as style guidance → the AI generates new course pages. For courses with >10 pages, this generation **must** run asynchronously through the workflow engine. The IMP file should have:

1. **In §1.1 "Architecture Integration Map":** An arrow from `SimilarCourseService` → `WorkflowOrchestrator` for the course generation path, labeled "for courses >10 pages, dispatch to workflow engine"
2. **In §1.3 "Modified Files":** An entry for `app/main.py` showing the workflow orchestrator startup wiring, and `app/services/workflow/steps/course_generation.py` as a new step that uses the RAG service
3. **In §9 "Chat Orchestrator Integration":** A note that when `_execute_mock_tool` triggers a multi-page generation, it should return a `workflow_id` instead of blocking
4. **In §17 "File Manifest":** A dependency section listing `PEND-01 (US-AI-034)` as a prerequisite for production page generation

### 5.2 Traceability Matrix: Architecture → IMP → Code

| Architecture Phase (Flow #3 v1.1) | IMP File Coverage | Code Coverage |
|-----------------------------------|-------------------|---------------|
| Phase 0: Edge & Intake | ✅ §7 (router), §10 (feature flag) | ✅ `ai_proposals.py` |
| **Phase 1: Async Worker** | ❌ **Not mentioned** | ❌ **65-line stub** |
| Phase 2: AI Safety & Routing | ✅ §9 (chat orchestrator) | ✅ `safety_service.py`, `model_tier_router.py` |
| Phase 3: Core AI Pipeline | ✅ §9 (context pruning, JSON repair) | ✅ `chat_orchestrator.py`, `context_manager.py` |
| Phase 4: Validation Pipeline | ✅ §9 (output guard) | ✅ `safety_service.py`, `validation_engine.py` |
| Phase 5: Proposal State Machine | ✅ Already existed | ✅ `proposal_service.py` |
| Phase 6: Human Review & RLHF | Partial (RLHF deferred to PEND-03) | Partial |
| Phase 7: Apply & Outbox | ✅ Already existed | ✅ `proposal_service.py`, `outbox_service.py` |
| Phase 8: Event Streaming | Partial (Kafka → PEND-02) | Partial (DB polling relay) |
| Phase 9: DLQ Recovery | ✅ Already existed | ✅ `dead_letter_queue.py` |
| Phase 10: Observability | ✅ Already existed | ✅ `ai_telemetry.py`, `cost_tracker.py` |

**Phase 1 is the ONLY phase with zero IMP coverage.** Every other phase has either a dedicated task, a code reference, or an explicit deferral notice.

### 5.3 The 5 Architecture Steps That Are Stubbed

From `Create Page Proposal and Apply Flow - Platform Runtime and Operations1.1.mmd`:

```
Phase 1 — Async Worker & Distributed State (B1 → B4 chain):

  B1: Job Queue (Kafka/SQS)           ← STUBBED
  B2: AI Orchestrator Worker          ← STUBBED  
  B3: Redlock Lease Manager           ← STUBBED
        (Acquire lock by job_id + Heartbeat renewal)
  B4: Checkpoint Loader               ← STUBBED
        (Restore Phase & Context)
```

Additionally, the v1.0 flow chart has a corresponding Phase 1 — "Workflow Engine Control Plane" (W1–W6) — referencing Temporal/Cadence orchestration of Activities (Retrieval, Planning, Validation, Preview, Apply) — also stubbed.

---

## 6. Impact Assessment

| Impact Area | Severity | Details |
|------------|----------|---------|
| **Production availability** | 🔴 Critical | Any course generation >30s fails on HTTP timeout. No recovery. |
| **Data integrity** | 🔴 Critical | Crash during generation = all progress lost, no checkpoint to resume from |
| **User experience** | 🔴 Critical | Users must wait synchronously for 2–15 minutes. Browser times out. |
| **SCORM export** | 🟡 High | Large courses (>80 pages) fail on export timeout |
| **Developer velocity** | 🟡 High | No async job framework means every new long-running feature reinvents the wheel |
| **Test coverage** | 🟡 High | Only 9 assertions test workflow concepts; no DB, API, or recovery tests |

---

## 7. Implementation Approach (PostgreSQL-Backed — Recommended)

Following the spec's detailed design (US-AI-034 §4–§8): build a PostgreSQL-backed state machine engine using `asyncio` for the worker loop. **No external dependency on Temporal.**

### Rationale for PostgreSQL-Backed Over Temporal

| Factor | PostgreSQL-Backed | Temporal.io |
|--------|------------------|-------------|
| New infrastructure | None (uses existing PostgreSQL) | Temporal cluster needed |
| Spec alignment | 100% — spec code is ready | Would need significant adaptation |
| Test infrastructure | Ready (19 standalone runners, SQLite override pattern) | Temporal test server needed |
| Effort | 3–5 days | 5–8 days + infra |
| Migration path | Can swap PostgreSQL orchestrator for Temporal later (same step functions, same API) | N/A |
| Production readiness | Proven pattern (SELECT FOR UPDATE SKIP LOCKED, heartbeat, checkpoint) | Battle-tested but overkill for MVP |

### Task Breakdown (from Spec §8)

| # | Task | SP | Key Deliverables |
|---|------|----|------------------|
| 8.1 | DB Schema & Alembic Migration | 3 | 3 ORM models (`WorkflowJob`, `WorkflowTypeDefinition`, `WorkflowJobEvent`), migration with 9 indexes, CHECK constraints |
| 8.2 | WorkflowRepository | 3 | 15+ async methods, `SELECT FOR UPDATE SKIP LOCKED`, atomic transitions via `UPDATE ... RETURNING` |
| 8.3 | WorkflowOrchestrator | 5 | Background asyncio poll loop, state machine runner, stale job recovery on startup, webhook delivery, concurrency limiting |
| 8.4 | Step Registry + Course Generation Steps | 3 | Decorator-based registry, 4 state steps for `course_generation`, LLM integration |
| 8.5 | REST Router | 3 | 6 endpoints with Pydantic schemas, `jsonschema` input validation, feature flag gating |
| 8.6 | Feature Flag + Env Config | 1 | `durable_workflow_engine` flag, 11 env vars |
| 8.7 | SCORM Export Step | 2 | 5-state export workflow, large/small routing |
| 8.8 | Observability | 2 | Structured log per state transition, optional OTel spans |
| 8.9 | Tests | 5 | 6 test files, 50+ scenarios, mocked LLMClient |
| 8.10 | Integration with DLQ | 1 | Failed jobs → DeadLetterQueue with exponential backoff |

**Total: ~28 story points / 3–5 days**

---

## 8. Test Coverage Required

The spec defines 6 test files with **62 test scenarios** (spec §7):

| Test File | Scenarios | Focus |
|-----------|-----------|-------|
| `tests/test_workflow_orm.py` | 4 | ORM model constraints, cascade deletes, default values |
| `tests/test_workflow_repository.py` | 15 | Lock acquisition, transitions, stale detection, heartbeat, event append |
| `tests/test_workflow_orchestrator.py` | 11 | State machine advancement, retries, timeouts, concurrency limit, recovery, webhooks, cancel |
| `tests/test_workflows_api.py` | 14 | All 6 endpoints, validation errors, feature flag gating, pagination, checkpoint sanitization |
| `tests/test_workflow_course_generation_e2e.py` | 7 | Full course generation lifecycle, page validation retry, LLM failure exhaustion, timeout, progress visibility, crash recovery, cancel mid-generation |
| `tests/test_export_workflow_integration.py` | 2 | Large course auto-routing to workflow, small course synchronous path |

Existing test in `tests/run_final_stories_tests.py` tests only the 65-line MVP — these new tests fully replace and expand it.

---

## 9. Environment & Configuration

11 new environment variables needed (from spec §5):

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKFLOW_WORKER_ID` | `worker-1` | Unique worker instance identifier for DB locks |
| `WORKFLOW_MAX_CONCURRENCY` | `4` | Maximum simultaneous job executions |
| `WORKFLOW_POLL_INTERVAL` | `1.0` | Seconds between pending-job poll cycles |
| `WORKFLOW_HEARTBEAT_INTERVAL` | `5.0` | Seconds between heartbeat updates for running jobs |
| `WORKFLOW_LOCK_TIMEOUT_MS` | `5000` | PostgreSQL `lock_timeout` for `SELECT FOR UPDATE` queries |
| `WORKFLOW_STALE_THRESHOLD` | `30` | Seconds without heartbeat to consider a job stale |
| `WORKFLOW_ENABLED` | `true` | Master kill switch — set `false` to disable background processing |
| `AI_GENERATION_MODEL` | `claude-sonnet-4-20250514` | Default LLM model for generation steps |
| `AI_GENERATION_RETRY_COUNT` | `3` | Page-level LLM retries on validation failure |
| `AI_GENERATION_TEMPERATURE` | `0.3` | LLM temperature for generation steps |
| `AI_GENERATION_MAX_TOKENS` | `4096` | Max tokens per page generation |

Feature flag: `FEATURE_DURABLE_WORKFLOW_ENGINE` (default: `false` for safety).

---

## 10. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| DB lock contention under load | Medium | High | `SKIP LOCKED` + `lock_timeout` 5s; 4-concurrency default is conservative |
| Checkpoint data exceeds 1MB | Low | Medium | Enforce 1MB limit at write; strip page content from API responses (already designed in spec §4.6 `_sanitize_checkpoint()`) |
| LLM call hangs in step | Medium | High | `asyncio.wait_for()` with per-state timeout; step timeout → dead-letter |
| Race condition: two workers claim same job | Low | High | `SELECT FOR UPDATE SKIP LOCKED` is atomic at DB level |
| Migration conflicts with existing tables | Low | Medium | New tables only; no existing table modifications |
| Feature flag disabled on deploy | Low | Medium | Orchestrator startup gated; all endpoints return 404 when disabled |

---

## 11. Summary Timeline

| Date | Event | Consequence |
|------|-------|------------|
| Sprint 5 planning | US-AI-034 spec written (MUST priority) | Clear blueprint exists |
| Sprint 5 implementation | 65-line `durable_workflow.py` + `AsyncPreviewJob` written | MVP stub created |
| Sprint 5 closure | INDEX.md marks 034 as "✅ COMPLETE, COULD" | Priority downgraded, gaps hidden |
| Sprint 5 test | `run_final_stories_tests.py` tests 9 basic assertions | Tests pass → false confidence |
| 2026-06-15 | VALIDATION_REPORT: "100% Compliant, 5 stubs" | Gap masked by methodology |
| 2026-06-20 | US-BKND-AI-015-IMP.md written (2,992 lines) | Zero workflow references — blind spot persists |
| 2026-06-20 | PENDING_TASKS_REPORT: "PEND-01 MUST, 3-5 days" | Gap formally identified |
| **2026-06-20** | **This RCA written** | **5 root causes documented, implementation path defined** |

---

## 12. Recommendations

### 12.1 Immediate (Before Production)

1. **Stop marking stories COMPLETE without enriched stories.** Every `✅ COMPLETE` in INDEX.md must have a corresponding `US-BKND-AI-XXX_enriched.md` with acceptance criteria, implementation tracking, and known gaps.

2. **Implement PEND-01 using the PostgreSQL-backed approach** (spec §4–§8). The epic spec provides complete, production-ready code for the orchestrator, repository, models, router, and step functions. No Temporal dependency needed for MVP.

3. **Add dependency checklists to all future IMP files.** Before any story marked COMPLETE, verify that all architecture flow phases it depends on are at production readiness.

### 12.2 Process Improvements

4. **ARCHITECTURE_VALIDATION should not count "stubs for future infrastructure" as compliant.** The 5 stubbed steps represent production-critical gaps. A separate metric ("production readiness" vs "architecture compliance") should track the distinction.

5. **INDEX.md should have a `production_ready` column** separate from `status`. A story can be "implemented" (65-line MVP) without being "production ready" (PostgreSQL-backed with recovery).

6. **Enriched story files should be prerequisites for marking COMPLETE**, not optional documentation. The absence of `US-BKND-AI-034_enriched.md` is the single strongest predictor of the implementation gap.

### 12.3 Specific Code Fixes

7. **Wire `durable_workflow.py` consumers:** Even before the full workflow engine is built, the existing 65-line MVP should be imported and used somewhere — for example, the `AsyncPreviewJob` class should back the actual preview generation endpoint.

8. **Add integration test:** A single test that creates a workflow job, advances it through steps, and verifies checkpoint data survives a simulated restart (by re-reading from DB) would catch the gap immediately.

---

## 13. References

| Reference | File | Description |
|-----------|------|-------------|
| Epic Spec | `docs/AI_Implemenation/00_User_StoriesUseCases/US-AI-034_DURABLE_WORKFLOW_ENGINE.md` | 2,299-line complete blueprint |
| Architecture Flow v1.1 | `docs/AI_Implemenation/01_SystemArchitecture/Create Page Proposal and Apply Flow - Platform Runtime and Operations1.1.mmd` | 49-step flow with 5 stubbed Phase-1 steps |
| Architecture Flow v1.0 | `docs/AI_Implemenation/01_SystemArchitecture/Create Page Proposal and Apply Flow1.0.mmd` | 9-phase flow with stubbed Workflow Engine phase |
| Validation Report | `docs/AI_Implemenation/01_SystemArchitecture/VALIDATION_REPORT.md` | §3 — Flow #3 validation: "100% Compliant, 5 stubs" |
| Pending Tasks Report | `docs/AI_Implemenation/01_SystemArchitecture/PENDING_TASKS_REPORT.md` | PEND-01: "🔴 MUST before production SLA" |
| INDEX.md | `docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/INDEX.md` | Line 88: "US-BKND-AI-034 ✅ COMPLETE, COULD" |
| IMP Playbook | `docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-015-IMP.md` | 2,992 lines — zero workflow references |
| Current MVP | `app/services/ai/durable_workflow.py` | 65 lines — in-memory, zero consumers |
| Dead Letter Queue | `app/services/ai/dead_letter_queue.py` | 281 lines — standalone, not integrated with workflow |
| Job Status Service | `app/services/ai/job_status_service.py` | 85 lines — standalone in-memory tracker |
| Test (MVP only) | `tests/run_final_stories_tests.py` | 9 assertions on DurableWorkflow + AsyncPreviewJob |
| CLAUDE.md | `CLAUDE.md` | Service layer docs reference `durable_workflow.py` |

---

**Document Version:** 1.0 — RCA & Implementation Gap Analysis
**Authored:** 2026-06-20
**TPO / Solutions Architect:** This document traces all 5 root causes of the PEND-01 gap,
maps the missing integration points in US-BKND-AI-015-IMP.md, and provides the complete
implementation path from the 2,299-line epic spec.
