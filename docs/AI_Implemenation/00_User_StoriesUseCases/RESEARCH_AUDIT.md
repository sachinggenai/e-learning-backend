# User Story Coverage & Completeness Audit

**Date:** 2026-06-14
**Audit Scope:** All 42 user stories (US-AI-001 through US-AI-042) against all architecture documents, flow charts, and codebase
**Methodology:** Exhaustive cross-reference of every use case, scenario, edge case, error path, and functional requirement from all source documents

---

## Part 1: Source Documents Audited

| Document | Type | Key Content |
|---|---|---|
| PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md | Architecture | Component diagram, 3 data-flow scenarios, tool contracts, session/state rules, validation pipeline, file ingestion, RAG strategy, security, failure modes, 10-chunk roadmap, system prompt |
| TOOL_SCHEMAS_CLAUDE_NATIVE.md | Tool Contracts | 12 tool schemas with full JSON input/output schemas, template data schemas, error response contract |
| AI_Session_Creation_Flow.mmd | Flow Chart | 15-step session creation with 8 error paths |
| Page_List_and_Fetch_Flow.mmd | Flow Chart | List + fetch flow with cache, lock, etag handling |
| Create Page Proposal and Apply Flow1.0.mmd | Flow Chart | 9-phase platform runtime: edge, workflow, RAG, multi-provider, generation, validation, preview, review, apply, outbox, offline eval |
| Create Page Proposal and Apply Flow - Platform Runtime and Operations1.1.mmd | Flow Chart | Async job queue version with Redlock, checkpoint, planner/generator separation |
| Create_Page_Proposal_and_Apply_Flow-old.mmd | Flow Chart | Detailed step-by-step with title uniqueness, media validation, cache invalidation, etag, sequence calc |
| Update_Page_Proposal_and_Apply_Flow.mmd | Flow Chart | 4-phase: session scope, proposal build, human review, apply with staleness |
| Delete_Page_Proposal_and_Confirm_Flow.mmd | Flow Chart | 4-phase with dependency check, risk preview, confirmation token |
| Course_Validation_Flow.mmd | Flow Chart | 4-phase: request entry, source-of-truth assembly, pipeline, result gating |
| Similar_Course_Retrieval_Flow.mmd | Flow Chart | 4-phase: query intake, retrieval strategy, result shaping, safety |
| File_Ingestion_Document_Import_Flow.mmd | Flow Chart | 5-phase: upload, extraction, segmentation, review, generation/apply |
| Full_Course_From_Uploaded_File_Scenario_Flow.mmd | Flow Chart | 5-phase: intake, extraction, page plan review, generate/validate, apply/commit |
| Simple_Chat_Edit_Scenario_Flow.mmd | Flow Chart | 4-phase: chat intake, state refresh, tool-enforced proposal, apply/audit |
| Destructive_Delete_Scenario_Flow.mmd | Flow Chart | 4-phase: intent/disambiguation, delete proposal, explicit confirm, apply/audit |
| Propose_Validate_Confirm_Apply_Safety_Flow.mmd | Flow Chart | 5-phase safety backbone with all error paths |
| CHUNK_0-2_DETAILED_TASK_BREAKDOWNS.md | Implementation | Detailed tasks for Chunks 0-2 with code examples, test cases, sign-off checklists |
| E2E_TEST_CASE_TEMPLATES.md | Testing | 12 test templates across Chunks 0-2 with automation scripts |
| DEVELOPER_ONBOARDING_GUIDE.md | Onboarding | Architecture overview, dev setup, chunk breakdown, troubleshooting |
| ARCHITECTURE_COMPARISON_ANALYSIS.md | Analysis | Gap analysis between attached docs and new production requirements |
| AI_IMPLEMENTATION_REFERENCE.md | Reference | Demo goals, template scope, model strategy, guardrails |
| AI_Architecture_Update_Log.md | Change Log | Document update history |

---

## Part 2: Use Case Coverage — Identified Gaps

### GAP-1: Concurrent Edit / Page Lock Conflict Handling
**Source:** Page_List_and_Fetch_Flow.mmd (LOCK_CHECK node), E2E_TEST_CASE_TEMPLATES.md
**Description:** When a user manually edits a page that an AI session has a stale proposal for, or when two AI sessions target the same page, the system must detect the conflict and return guidance. The flow shows "Check page lock/status for concurrent edits" with a 409 response and "Show lock owner & option to request takeover."
**Current coverage:** No story explicitly covers page locking, lock takeover, or concurrent edit conflict resolution.
**Recommendation:** Add to US-AI-010 (apply safety) or create a dedicated story for concurrency control.

### GAP-2: Page Title Uniqueness Enforcement
**Source:** Create_Page_Proposal_and_Apply_Flow-old.mmd (TITLE_CHECK node)
**Description:** When AI proposes a new page, the backend must validate that the title is unique within the course. Duplicate titles return 409 with "Title already exists."
**Current coverage:** Not explicitly mentioned in US-AI-011 or any other story.
**Recommendation:** Add to US-AI-011 acceptance criteria or technical details.

### GAP-3: Media/Asset Reference Validation in AI Context
**Source:** Create_Page_Proposal_and_Apply_Flow-old.mmd (CHECK_MEDIA node)
**Description:** When AI-generated content references media (images, video, audio), those references must be validated against existing assets or flagged as unresolved.
**Current coverage:** Not covered. US-AI-016 covers file upload but not how AI-generated pages reference/validate media assets.
**Recommendation:** Add to US-AI-011 or create a dedicated validation rule in US-AI-008.

### GAP-4: Cache Invalidation After AI Mutations
**Source:** Create_Page_Proposal_and_Apply_Flow-old.mmd (INVALIDATE_CACHE node), Page_List_and_Fetch_Flow.mmd (CACHE_CHECK)
**Description:** After AI mutations (create/update/delete), cached course/page data must be invalidated so subsequent reads return fresh data. The flow shows explicit cache invalidation after DB insert.
**Current coverage:** Not covered. The re-fetch rule is in US-AI-007 but cache management strategy is not a standalone concern.
**Recommendation:** Add to US-AI-010 (as part of apply transaction) or to US-AI-028 (context pruning touches caching).

### GAP-5: ETag / Optimistic Concurrency for AI Operations
**Source:** Page_List_and_Fetch_Flow.mmd, Create_Page_Proposal_and_Apply_Flow-old.mmd
**Description:** Pages are served with ETags for cache validation. AI proposals should use ETags or content hashes to detect stale data.
**Current coverage:** US-AI-010 mentions "base hash" for staleness but doesn't detail the ETag mechanism.
**Recommendation:** Enhance US-AI-010 technical details with ETag/version-based concurrency.

### GAP-6: Distributed Lock for Async AI Workers
**Source:** Create Page Proposal and Apply Flow - Platform Runtime and Operations1.1.mmd (Redlock Lease Manager)
**Description:** When AI jobs run on distributed workers, a Redlock (distributed lock manager) acquires locks by job_id with heartbeat renewal to prevent duplicate processing.
**Current coverage:** US-AI-034 mentions workflow engine but doesn't detail distributed locking.
**Recommendation:** Add to US-AI-034 technical details.

### GAP-7: Planner Model vs Generator Model Separation
**Source:** Create Page Proposal and Apply Flow - Platform Runtime and Operations1.1.mmd (LLM Planner vs LLM Generator)
**Description:** The architecture describes two tiers of AI models: a fast/cheap "Planner" that determines structure and template selection, and a premium "Generator" that produces schema-bound content.
**Current coverage:** US-AI-026 mentions model routing but doesn't explicitly separate planner and generator concerns.
**Recommendation:** Add to US-AI-026 or create a dedicated story.

### GAP-8: Cross-Encoder RAG Reranker
**Source:** Create Page Proposal and Apply Flow1.0.mmd (Cross-Encoder Reranker), Similar_Course_Retrieval_Flow.mmd
**Description:** After initial vector search, a cross-encoder reranks top-K results for relevance before returning to the LLM.
**Current coverage:** US-AI-015 covers RAG retrieval but doesn't mention reranking.
**Recommendation:** Add to US-AI-015 technical details.

### GAP-9: AI-Specific API Gateway Configuration
**Source:** Create Page Proposal and Apply Flow1.0.mmd (API Gateway node)
**Description:** The platform runtime flow shows an API Gateway handling tenant isolation, rate limits, and quota checks before AI requests reach the service layer.
**Current coverage:** US-AI-021 covers rate limits at the service level but not at the gateway level.
**Recommendation:** Add to US-AI-021 or create a gateway configuration story.

### GAP-10: Database Migration Strategy for AI Tables
**Source:** CHUNK_0-2_DETAILED_TASK_BREAKDOWNS.md (implicit in all persistence tasks)
**Description:** New AI tables (ai_sessions, ai_proposals, ai_audit_logs, outbox_events, etc.) require Alembic migrations with rollback scripts.
**Current coverage:** No story explicitly covers database migrations.
**Recommendation:** Add migration requirement to US-AI-004 (persistence foundations).

### GAP-11: SCORM Scoring Integration for AI-Generated Assessments
**Source:** FINAL_ASSESSMENT_BA_REVIEW.md, Course_Validation_Flow.mmd (SCORM compliance check)
**Description:** AI-generated final-assessment pages must include proper SCORM scoring configuration (max score, passing score, question-level correct answers) that integrates with the existing SCORM runtime.
**Current coverage:** US-AI-038 covers SCORM export readiness but doesn't specifically address assessment scoring integration.
**Recommendation:** Add to US-AI-038 or merge into US-AI-008 (validation pipeline).

### GAP-12: Frontend Polling/SSE for Async Job Status
**Source:** File_Ingestion_Document_Import_Flow.mmd (polling), Full_Course_From_Uploaded_File_Scenario_Flow.mmd
**Description:** The frontend needs a mechanism (polling, SSE, or WebSocket) to receive real-time status updates on long-running AI jobs (file ingestion, batch generation).
**Current coverage:** US-AI-024 mentions session management but not real-time job status updates. US-AI-041 mentions preview polling.
**Recommendation:** Add to US-AI-024 or create a dedicated frontend real-time updates story.

### GAP-13: Environment-Specific AI Configuration Profiles
**Source:** PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md (Appendix A), CHUNK_0-2_DETAILED_TASK_BREAKDOWNS.md
**Description:** AI configuration (model selection, rate limits, cost caps, feature flags) must differ by environment: dev (loose limits, cheap models), staging (production-like), production (strict limits, best models).
**Current coverage:** US-AI-002 mentions configuration but doesn't address environment-specific profiles.
**Recommendation:** Add to US-AI-002 technical details.

### GAP-14: PII/Secret Redaction in AI Prompts and Logs
**Source:** PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md (Section 9.5)
**Description:** Before logging or storing AI requests, sensitive fields (passwords, API keys, tokens, PII) must be redacted. The architecture specifies redaction paths and JSON redaction logic.
**Current coverage:** US-AI-025 covers prompt safety (injection/PII scanning at intake) but doesn't explicitly cover PII redaction in audit logs.
**Recommendation:** Add to US-AI-025 or US-AI-020 (admin audit).

### GAP-15: AI Session Cleanup / Garbage Collection
**Source:** Session management flows (implicit expiry)
**Description:** Expired AI sessions, proposals, and confirmation tokens need periodic cleanup to prevent storage bloat.
**Current coverage:** US-AI-006 mentions session expiry but doesn't address cleanup. US-AI-004 mentions TTL but not garbage collection.
**Recommendation:** Add to US-AI-004 or US-AI-006.

### GAP-16: Prompt Template Variables / Dynamic System Prompt Assembly
**Source:** PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md (System Prompt section)
**Description:** The system prompt needs to be dynamically assembled per session: injected with the current course context, available templates, user role, and organization policies.
**Current coverage:** US-AI-042 covers prompt versioning/A-B testing but not the dynamic assembly of prompt variables.
**Recommendation:** Add to US-AI-042 or US-AI-023 (chat orchestrator).

### GAP-17: AI Content Branching / Navigation Validation
**Source:** Delete_Page_Proposal_and_Confirm_Flow.mmd (Dependency Check)
**Description:** When AI deletes or reorders pages, branching configurations and navigation references must be validated and repaired.
**Current coverage:** US-AI-013 mentions dependency checking but doesn't detail branching/navigation repair.
**Recommendation:** Add to US-AI-013 technical details.

### GAP-18: Multi-Language / i18n Support for AI Content
**Source:** Not explicitly in current docs but implied by multi-tenant architecture
**Description:** AI-generated content may need to be generated in the user's preferred language. The system should support language selection per session.
**Current coverage:** Not covered.
**Recommendation:** COULD priority — add as a future story if needed.

### GAP-19: AI Content Deduplication / Similarity Detection
**Source:** Not explicitly mentioned but implied by template harvesting
**Description:** Before creating AI pages, check for content similarity with existing pages to avoid duplication.
**Current coverage:** Not covered.
**Recommendation:** COULD priority — add to US-AI-037 (template harvesting) or as validation rule in US-AI-008.

### GAP-20: Circuit Breaker for AI Provider Failures
**Source:** PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md (Failure & Fallback, Section 10.2)
**Description:** After N consecutive failures to a provider, the circuit breaker opens and routes to fallback for a cooldown period.
**Current coverage:** US-AI-026 mentions fallback but doesn't detail circuit breaker pattern.
**Recommendation:** Add to US-AI-026 technical details.

---

## Part 3: Story Completeness Assessment

Each story evaluated on whether a developer could implement it independently. Rating scale:
- ✅ **Self-contained** — Has enough context for independent implementation
- ⚠️ **Needs more context** — Missing key details (API contract, schema, error handling, edge cases)
- ❌ **Insufficient** — Major gaps; developer would need to ask many questions

### US-AI-001: Preserve Manual Authoring ⚠️
**Missing:** Specific list of which existing routes/tests must remain unchanged. List of "do not touch" files/modules. Regression test checklist.
**Recommendation:** Add explicit non-regression contract: list of routes, services, and tests that must pass unchanged.

### US-AI-002: Feature Flags and Model Config ✅
**Missing:** Environment-specific configuration profiles (dev/staging/prod). Config hot-reload mechanism.
**Recommendation:** Add GAP-13 (environment profiles). Clarify whether config changes require restart.

### US-AI-003: Isolated AI API Module ✅
**Missing:** Exact module tree. Router registration pattern. Error envelope contract reference.
**Recommendation:** Add explicit file tree and the error envelope schema.

### US-AI-004: AI Persistence Foundations ⚠️
**Missing:** Complete table schemas with column types. Migration strategy. Garbage collection policy for expired records. Index strategy.
**Recommendation:** Add DDL for each table. Add GAP-10 (migrations) and GAP-15 (cleanup).

### US-AI-005: Tool and Template Contract Registry ✅
**Missing:** Version numbering scheme. Deprecation policy for old tool versions.
**Recommendation:** Minor — add versioning policy.

### US-AI-006: AI Session Creation ⚠️
**Missing:** Session authorization header format (`Authorization: Session {sessionId}`). Session storage backend (Redis vs in-memory). Cross-tenant isolation verification step.
**Recommendation:** Add auth header spec. Add session storage architecture decision.

### US-AI-007: Page List and Fetch Tools ⚠️
**Missing:** Pagination parameters. ETag header format. Cache TTL configuration. Lock information in response.
**Recommendation:** Add pagination contract. Add ETag spec. Add GAP-1 (lock handling).

### US-AI-008: Course and Page Validation Pipeline ⚠️
**Missing:** Complete list of validation rules per template. Error code catalog. Validation scope options. SCORM scoring integration for assessments.
**Recommendation:** Add validation rule catalog. Add GAP-11 (SCORM scoring).

### US-AI-009: Generic Proposal Lifecycle ✅
**Missing:** Minor — proposal TTL configuration. State transition diagram.
**Recommendation:** Add state machine diagram reference.

### US-AI-010: Apply Safety, Audit, and Outbox ⚠️
**Missing:** Idempotency key format and generation. ETag-based staleness check. Cache invalidation step. Transaction boundaries for audit/outbox writes.
**Recommendation:** Add GAP-4 (cache invalidation) and GAP-5 (ETag). Detail idempotency key spec.

### US-AI-011: Create Page Proposal and Apply ⚠️
**Missing:** Title uniqueness check. Media reference validation. Page order/sequence calculation. Insert position semantics (insertAtIndex).
**Recommendation:** Add GAP-2 (title uniqueness) and GAP-3 (media validation). Add ordering semantics.

### US-AI-012: Update Page Proposal and Apply ⚠️
**Missing:** Allowed patch fields catalog. Component-level patching. Partial vs full data replacement semantics.
**Recommendation:** Add explicit patch field allowlist. Add component patching strategy.

### US-AI-013: Delete Page Proposal and Confirm ⚠️
**Missing:** Dependency check catalog (branching, navigation, scoring, final assessment, export). Page reorder after delete. Undo window configuration.
**Recommendation:** Add GAP-17 (branching/navigation repair). Add dependency check rules.

### US-AI-014: Simple Chat Edit Orchestration ✅
**Missing:** Chat turn TTL. Conversation history limit. Ambiguity resolution protocol.
**Recommendation:** Minor — add conversation management details.

### US-AI-015: Similar Course Retrieval ⚠️
**Missing:** Vector index technology choice. Reranker algorithm. Embedding model. Index refresh schedule. Tenant partition strategy.
**Recommendation:** Add GAP-8 (reranker). Add indexing architecture decisions.

### US-AI-016: File Upload and Ingestion Foundation ✅
**Missing:** Supported MIME types catalog. Virus scanning integration point. File size limits. Storage backend.
**Recommendation:** Add explicit file policy configuration.

### US-AI-017: Document Extraction and Page-Plan Review ⚠️
**Missing:** Extraction quality thresholds. OCR fallback for scanned docs. Merge/split/reorder API contract. Source coverage validation rules.
**Recommendation:** Add extraction quality metrics. Add review API contract.

### US-AI-018: Validation Report UI ✅
**Missing:** UI component specification. Interactivity details (jump to page, filter by severity).
**Recommendation:** Minor — add UI interaction details.

### US-AI-019: Full Course from Uploaded File ⚠️
**Missing:** Batch proposal API contract. Progress tracking granularity. Partial failure recovery UX. Template deduplication during harvest.
**Recommendation:** Add batch API contract. Add progress tracking spec.

### US-AI-020: Admin Audit and Recovery ⚠️
**Missing:** Audit query API contract. Filter parameters. Rollback proposal generation. Before/after diff format.
**Recommendation:** Add audit query API spec. Add rollback proposal format.

### US-AI-021: Observability, Rate Limits, Rollout ⚠️
**Missing:** Metrics catalog. Dashboard requirements. 429 response format. Rollout percentage configuration. Trace ID format.
**Recommendation:** Add GAP-9 (gateway configuration). Add metrics spec.

### US-AI-022: End-to-End Regression Suite ✅
**Missing:** Test data fixtures. Mock LLM response format. CI pipeline integration.
**Recommendation:** Minor — add test infrastructure details.

### US-AI-023: AI Chat Endpoint and Orchestration ⚠️
**Missing:** Streaming response format (SSE vs chunked). Max tool-call rounds configuration. System prompt injection point. Chat turn persistence schema.
**Recommendation:** Add streaming spec. Add GAP-16 (dynamic prompt assembly). Add chat turn schema.

### US-AI-024: Frontend AI Integration Layer ✅
**Missing:** Component tree. State management pattern. Error boundary strategy. Session expiry UX.
**Recommendation:** Add GAP-12 (real-time job status). Add component architecture.

### US-AI-025: Prompt Safety and Content Guardrails ⚠️
**Missing:** PII detection rules catalog. Injection pattern library. Toxicity model choice. Blocklist management. GAP-14 (log redaction).
**Recommendation:** Add detection rule catalog. Add GAP-14.

### US-AI-026: Multi-Provider Model Routing ⚠️
**Missing:** Circuit breaker configuration. Provider health check. Model capability matrix. Cost optimization rules. GAP-7 (planner vs generator separation).
**Recommendation:** Add GAP-20 (circuit breaker). Add GAP-7 (two-tier model architecture).

### US-AI-027: JSON Repair and Recovery ✅
**Missing:** Repair strategy catalog. Fast model configuration. Repair attempt limits. Common error patterns.
**Recommendation:** Minor — add repair strategy details.

### US-AI-028: Context Pruning and Token Optimization ✅
**Missing:** Pruning algorithm. Relevance scoring for templates. Token counting method. Savings tracking format.
**Recommendation:** Minor — add pruning algorithm details.

### US-AI-029: Batch Proposal Operations ⚠️
**Missing:** Batch API contract (propose + apply). All-or-nothing rollback semantics. Partial approval UX. Batch size limits.
**Recommendation:** Add batch API contract. Add rollback semantics.

### US-AI-030: Course Assembly into Editor ✅
**Missing:** Data transformation mapping (proposal → editor state). Component type compatibility matrix. Editor event integration.
**Recommendation:** Minor — add data transformation spec.

### US-AI-031: RLHF Feedback and Provenance ⚠️
**Missing:** Feedback store schema. Edit distance algorithm. Aggregate metrics computation. Provenance manifest schema.
**Recommendation:** Add feedback schema. Add metrics computation spec.

### US-AI-032: Policy Engine for Auto-Apply ⚠️
**Missing:** Policy rule schema. Risk scoring algorithm. Policy change propagation. Default policy catalog.
**Recommendation:** Add policy rule DSL. Add default policy set.

### US-AI-033: Event-Driven Outbox ⚠️
**Missing:** Outbox table schema. Publisher mechanism (polling vs LISTEN/NOTIFY). Message broker choice. Consumer contract. At-least-once delivery details.
**Recommendation:** Add outbox schema. Add publisher architecture.

### US-AI-034: Durable Workflow Engine ⚠️
**Missing:** Workflow state machine. Checkpoint data schema. Human-in-the-loop signal API. Timeout/recovery behavior. GAP-6 (distributed lock).
**Recommendation:** Add workflow schema. Add GAP-6.

### US-AI-035: AI Content Accessibility ⚠️
**Missing:** WCAG rule catalog per template. Accessibility score algorithm. Remediation hint catalog. Screen reader testing strategy.
**Recommendation:** Add accessibility rule catalog.

### US-AI-036: Cost Tracking and Token Budget ⚠️
**Missing:** Usage record schema. Cost calculation per model. Budget notification thresholds. Usage API contract.
**Recommendation:** Add usage schema. Add notification spec.

### US-AI-037: Template Definition Harvesting ⚠️
**Missing:** Signature hashing algorithm. Similarity threshold. Admin review workflow. Promotion API contract.
**Recommendation:** Add harvesting algorithm. Add review workflow.

### US-AI-038: SCORM Export Readiness for AI ⚠️
**Missing:** Export compatibility rules per template. Export validation integration point. Unsupported component handling. GAP-11 (SCORM scoring).
**Recommendation:** Add GAP-11. Add export rule catalog.

### US-AI-039: Session Context Window Recovery ⚠️
**Missing:** Token counting method. Context threshold (80% of what?). Rehydration prompt template. Session summary schema.
**Recommendation:** Add token counting spec. Add rehydration prompt.

### US-AI-040: AI Content Versioning and Rollback ⚠️
**Missing:** Before-snapshot storage format. Rollback API contract. Rollback proposal format. Undo window configuration.
**Recommendation:** Add rollback API spec. Add snapshot format.

### US-AI-041: Async Preview Generation ⚠️
**Missing:** Preview job queue architecture. Preview storage format. Polling interval. Render timeout. Failed preview retry.
**Recommendation:** Add preview job spec. Add polling contract.

### US-AI-042: System Prompt Versioning and A/B ⚠️
**Missing:** Prompt version schema. Cohort assignment algorithm. Statistical significance method. Rollback mechanism. GAP-16 (dynamic assembly).
**Recommendation:** Add GAP-16. Add cohort assignment algorithm.

---

## Part 4: Summary Statistics

| Metric | Count |
|---|---|
| Total user stories | 42 |
| Stories rated ✅ Self-contained | 8 |
| Stories rated ⚠️ Needs more context | 34 |
| Stories rated ❌ Insufficient | 0 |
| Identified use case gaps (GAPs) | 20 |
| Gaps requiring new stories | 3 (GAP-1, GAP-7, GAP-12) |
| Gaps fixable by enhancing existing stories | 17 |

## Part 5: Recommended Actions

### Priority 1 — Add missing use cases as new stories:

1. **US-AI-043: Concurrency Control and Page Locking** (GAP-1)
   - Source: Page_List_and_Fetch_Flow.mmd (LOCK_CHECK), E2E test templates
   - How AI sessions handle concurrent manual/AI edits to the same page
   - Page lock acquisition, lock owner display, takeover requests
   - 409 conflict responses with lock metadata

2. **US-AI-044: Two-Tier Model Architecture (Planner + Generator)** (GAP-7)
   - Source: Platform Runtime flow 1.0 (Phases 3-4), flow 1.1 (Phase 3)
   - Fast/cheap planning model for structure decisions, premium model for content generation
   - Model tier assignment per task type, cost optimization rules

3. **US-AI-045: Real-Time Job Status and Notifications** (GAP-12)
   - Source: File_Ingestion_Document_Import_Flow.mmd, Full_Course_From_Uploaded_File_Scenario_Flow.mmd
   - Frontend polling, SSE, or WebSocket for async job progress
   - Progress granularity, connection recovery, timeout handling

4. **US-AI-046: Course-Level AI Operations** (from agent findings)
   - Source: Gap identified in chunk breakdowns analysis — 12 tools cover page CRUD but no course create/delete via AI
   - AI-assisted course creation from scratch (empty course shell)
   - AI-assisted course deletion with destructive confirmation
   - Course metadata generation (title, description, learning objectives)

5. **US-AI-047: Multi-User Collaboration on AI-Authored Courses** (from agent findings)
   - Source: Session model is strictly single-user/single-course; collaboration not addressed
   - Multiple instructors collaborating on AI-generated content
   - Shared session or session handoff, conflict resolution between users

6. **US-AI-048: Dead Letter Queue and Failed Job Recovery** (from agent findings)
   - Source: Platform Runtime flow 1.1 (Phase 9)
   - DLQ for AI jobs exceeding max retries
   - Operations dashboard with alerts, triage, and replay
   - Bulk requeue for transient provider outages

7. **US-AI-049: Confirmation Token System** (from agent findings)
   - Source: Delete_Page_Proposal_and_Confirm_Flow.mmd, Propose_Validate_Confirm_Apply_Safety_Flow.mmd
   - Token generation, validation, binding to session/proposal/page-hash
   - Token expiry, one-time-use enforcement, replay protection

8. **US-AI-050: Stale Detection and Merge Resolution** (from agent findings)
   - Source: Update flow, Safety flow, Platform Runtime flow 1.1 (Phase 7)
   - Hash-based staleness detection with ETags
   - Merge strategy for concurrent edits (last-write-wins vs. three-way merge)
   - User-facing conflict resolution UX

### Priority 2 — Enhance existing stories with missing context:

**API Contract Details needed for 34 ⚠️-rated stories:**
- Exact request/response JSON shapes (use TOOL_SCHEMAS_CLAUDE_NATIVE.md as reference)
- HTTP status codes per error scenario
- Authentication header format (`Authorization: Session {sessionId}`)
- Pagination parameters (list_pages)
- ETag header conventions

**Database Schema DDL needed for persistence stories:**
- US-AI-004: `ai_sessions`, `ai_proposals`, `ai_confirmation_tokens`, `ai_audit_logs`, `outbox_events`
- US-AI-016: `ai_ingestion_jobs` or extend `import_jobs`
- US-AI-020: Audit query indices and partitioning
- US-AI-031: `ai_feedback_events`, `ai_provenance_records`
- US-AI-033: `outbox_events` with publisher state columns
- US-AI-034: `ai_workflow_runs`, `ai_workflow_checkpoints`
- US-AI-036: `ai_usage_records` with tenant/user partitioning
- US-AI-042: `ai_prompt_versions`

**Error Code Catalogs needed:**
- US-AI-008: All validation error codes per template type
- US-AI-009: Proposal lifecycle error codes (expired, stale, mismatched, already-applied)
- US-AI-025: Safety violation codes (PII detected, injection detected, toxic output, blocked term)

**Configuration Values to specify:**
- Session TTL (currently "24h default" — make configurable range explicit)
- Proposal TTL (not specified anywhere)
- Cache TTL for page lists and page content
- Rate limit thresholds (100 calls/hour, 500 calls/day — are these defaults or requirements?)
- Max tool-call rounds per chat turn (currently "default 10" in US-AI-023)
- Max retries for JSON repair (currently "default 2" in US-AI-027)
- Context window threshold (currently "80% of model max" in US-AI-039)
- File size limits for uploads
- Supported MIME types for document ingestion

**Edge Cases to add:**
- US-AI-011: Duplicate page title within course, media reference validation, insert at specific position vs append
- US-AI-012: Patch to a page that was deleted between proposal and apply, component-level partial updates
- US-AI-013: Deleting the last page in a course, deleting a page referenced by branching, deleting a final assessment page
- US-AI-023: Chat turn with zero tool calls, chat turn exceeding max rounds, conversation history overflow
- US-AI-034: Workflow stuck in human-in-the-loop for days, workflow worker crash mid-phase, duplicate workflow signals

### Priority 3 — Add cross-cutting concerns to existing stories:
- Database migration strategy → add to US-AI-004
- Cache invalidation after AI mutations → add to US-AI-010
- Environment-specific configuration profiles → add to US-AI-002
- Session/proposal garbage collection → add to US-AI-004
- Circuit breaker for AI providers → add to US-AI-026
- Content deduplication/similarity detection → add to US-AI-008
- SCORM scoring integration for AI assessments → add to US-AI-038
- i18n/language selection per AI session → add as future consideration
- Page lock takeover semantics → add to new US-AI-043
- Frontend polling vs SSE decision → add to new US-AI-045
