# E-Learning Backend — AI Authoring Context

## Branch: `demo-course-AI`

All backend AI user stories (47/47) are implemented and pushed. 834 tests across 20 test suites. To resume work, read the commits on this branch — they contain the full implementation history.

### Key Git Commits (recent first, on demo-course-AI)

```
7737eb2 chore: update OpenAPI schema with all 44 AI endpoints
2406e8f feat: complete all 47 backend AI user stories (100%)
f6d4f1b feat: implement 17 backend AI user stories (44/47 complete, 93.6%)
f93257f added user storeis
c45422b added some userstories
119518d AI docs
699809a Page proposal arch
751371b AI research
```

Run `git log demo-course-AI --not main --oneline` for the full list. Use `git show <hash>` or `git diff main..demo-course-AI` to inspect changes.

### Architecture Overview

The AI subsystem lives under `app/services/ai/`, `app/routers/ai_*.py`, `app/models/ai_*.py`, `app/repositories/ai_*.py`, and `app/schemas/ai_*.py`. Middleware is in `app/middleware/`.

**Service layer** (`app/services/ai/`):
- `confirmation_token_service.py` — HMAC-SHA256 scope-bound tokens for destructive ops
- `proposal_service.py` — Proposal lifecycle (create, apply, cancel, delete with tokens)
- `chat_orchestrator.py` — LLM interaction loop + mock intent parser
- `llm_client.py` — Anthropic + Mock provider abstraction with SSE streaming
- `safety_service.py` — 3-layer guard: input injection (9 patterns), PII (10 patterns), output blocking
- `json_repair.py` — 12-strategy deterministic JSON repair pipeline
- `context_manager.py` — Token counting + 3 pruning strategies
- `course_generator.py` — Mock content generation for 5 template types
- `course_assembler.py` — Proposal-to-editor-state transformation
- `dependency_analyzer.py` — Branching/scoring/navigation impact analysis
- `cost_tracker.py` — Post-billing usage recording + budget enforcement
- `lock_manager.py` — READ/WRITE/SESSION locks with heartbeat + expiry
- `stale_detector.py` — 3-way merge + conflict reporting
- `dead_letter_queue.py` — Failure classification + exponential backoff retry
- `model_tier_router.py` — Planner (haiku) vs Generator (sonnet) task routing
- `policy_engine.py` — Rule-based auto-apply decisions
- `durable_workflow.py` — MVP checkpoint/retry (65-line stub, superseded by workflow engine below)
- `job_status_service.py` — Async job tracking + course-level operations
- `workflow/` (package) — **NEW (US-BKND-AI-034):** PostgreSQL-backed durable workflow engine
  - `orchestrator.py` — Background asyncio poll loop, state machine, crash recovery
  - `step_registry.py` — Shared singleton decorator-based registry (B1 fix)
  - `types.py` — StepResult dataclass, WorkflowStatus enum
  - `steps/course_generation.py` — 4 states: validate_input → generate_pages → validate_course → create_batch_proposal
  - `steps/scorm_export.py` — 5 states: validate_course → generate_manifest → package_assets → create_zip → complete
- `audit_query_service.py` — Filtered audit log querying + compliance summaries
- Plus: `config.py`, `diff_engine.py`, `error_envelope.py`, `idempotency_service.py`, `outbox_service.py`, `audit_service.py`, `session_service.py`, `ingestion_service.py`, `template_contracts.py`, `tool_executor.py`, `validation_engine.py`, mock services

**Router layer** (`app/routers/`):
- `ai_chat.py` — POST /chat, POST /chat/stream (SSE), GET /chat/history
- `ai_proposals.py` — CRUD + delete-page + confirm-delete
- `ai_confirmations.py` — POST /proposals/{id}/confirm
- `ai_admin.py` — safety-events, audit-logs, audit-summary, safety-stats
- `ai_ingestion.py` — upload + generate-course + review-plan
- `ai_sessions.py`, `ai_config.py`, `ai_templates.py`, `ai_tools.py`
- `workflows.py` — **NEW (US-BKND-AI-034):** 6 endpoints (submit, status, cancel, retry, events, list)

**Middleware** (`app/middleware/`):
- `ai_telemetry.py` — Trace ID propagation + request timing
- `ai_rate_limiter.py` — Per-user/per-tenant/per-endpoint sliding window rate limits

**Models** (`app/models/`):
- `ai_models.py` — 8 ORM models (sessions, proposals, confirmation tokens, audit, outbox, chat turns, idempotency, ingestion jobs)
- `workflow.py` — 3 ORM models (type definitions, jobs with heartbeat/locking, job events)
- `ai_admin_override.py` — Admin bypass audit trail
- `ai_safety_event.py` — Safety event persistence

### Test Suite

20 standalone test runners in `tests/run_*.py`. Each is a self-contained script that runs independently:

```
tests/run_confirmation_token_tests.py    (67 tests)
tests/run_delete_proposal_tests.py       (46 tests)
tests/run_chat_endpoint_tests.py         (74 tests)
tests/run_safety_guardrails_tests.py     (57 tests)
tests/run_json_repair_tests.py           (54 tests)
tests/run_context_pruning_tests.py       (33 tests)
tests/run_course_generation_tests.py     (37 tests)
tests/run_observability_tests.py         (28 tests)
tests/run_course_assembler_tests.py      (29 tests)
tests/run_concurrency_tests.py           (43 tests)
tests/run_cost_tracking_tests.py         (41 tests)
tests/run_stale_detection_tests.py       (32 tests)
tests/run_dlq_tests.py                   (23 tests)
tests/run_model_tier_tests.py            (25 tests)
tests/run_e2e_regression_tests.py        (28 tests)
tests/run_audit_admin_tests.py           (16 tests)
tests/run_job_course_ops_tests.py        (10 tests)
tests/run_final_stories_tests.py         (19 tests)
tests/run_workflow_engine_tests.py       (146 tests)
```

All 834 tests pass. Run individually with `PYTHONPATH=. python tests/run_<name>.py`.

Note: pytest segfaults in this environment (exit code 139) — use the standalone runners or run with PowerShell.

### Documentation

User story specs: `docs/AI_Implemenation/00_User_StoriesUseCases/`
- `backend-userstories/INDEX.md` — Status of all 47 stories (all COMPLETE)
- `backend-userstories/US-BKND-AI-*.md` — Enriched implementation notes for each story
- `US-AI-*.md` — Full epic specifications for each story

### Configuration

See `.env.example` for all AI-related environment variables. Key ones:
- `AI_AUTHORING_ENABLED` — Master switch (default: false)
- `ANTHROPIC_API_KEY` — Required for production LLM calls
- Rate limits, token budgets, safety modes, context window, confirmation TTLs

### Running the App

```
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload
```

OpenAPI schema: `openapi-current.json` (169 paths, including 44 AI endpoints).
