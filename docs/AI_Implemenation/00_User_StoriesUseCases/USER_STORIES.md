# Canonical User Stories - AI Authoring

## Purpose

This backlog refactors the AI authoring use-case flow charts into implementable user stories. The stories are ordered from the most independent foundations to dependent end-to-end scenarios, so each story should only depend on stories listed before it.

## Source Flow Coverage

| Flow | Covered by stories |
|---|---|
| 1. AI Session Creation Flow | US-AI-006 |
| 2. Page List and Fetch Flow | US-AI-007 |
| 3. Create Page Proposal and Apply Flow | US-AI-011 |
| 4. Update Page Proposal and Apply Flow | US-AI-012 |
| 5. Delete Page Proposal and Confirm Flow | US-AI-013 |
| 6. Course Validation Flow | US-AI-008, US-AI-018 |
| 7. Similar Course Retrieval Flow | US-AI-015 |
| 8. File Ingestion / Document Import Flow | US-AI-016, US-AI-017, US-AI-019 |
| 9. Simple Chat Edit Scenario Flow | US-AI-014 |
| 10. Full Course from Uploaded File Scenario Flow | US-AI-019 |
| 11. Destructive Delete Scenario Flow | US-AI-013 |
| 12. Propose, Validate, Confirm, Apply Safety Flow | US-AI-009, US-AI-010 |
| 13. Platform Runtime and Operations Flow | US-AI-026, US-AI-028, US-AI-029, US-AI-032, US-AI-033, US-AI-034, US-AI-036, US-AI-041 |
| 14. AI Chat Orchestration and LLM Interaction Loop | US-AI-023 |
| 15. Prompt Safety and Content Guardrails | US-AI-025 |
| 16. JSON Repair and Structured Output Recovery | US-AI-027 |
| 17. Frontend AI Integration Layer | US-AI-024 |
| 18. Course Assembly into Existing Editor | US-AI-030 |
| 19. Batch Proposal and All-or-Nothing Semantics | US-AI-029 |
| 20. RLHF Feedback and Provenance Tracking | US-AI-031 |
| 21. Policy Engine for Auto-Apply Decisions | US-AI-032 |
| 22. Durable Workflow Engine for Long-Running Jobs | US-AI-034 |
| 23. AI Content Accessibility Compliance | US-AI-035 |
| 24. Cost Tracking and Token Budget Enforcement | US-AI-036 |
| 25. Template Definition Harvesting | US-AI-037 |
| 26. SCORM Export Readiness for AI Content | US-AI-038 |
| 27. Session Context Window Recovery | US-AI-039 |
| 28. AI Content Versioning and Rollback | US-AI-040 |
| 29. Async Preview Generation Service | US-AI-041 |
| 30. System Prompt Versioning and A/B Testing | US-AI-042 |

## Current Backend Alignment

- Existing reusable backend surfaces: `/api/v1/courses`, `/api/v1/courses/{courseId}/pages`, `/api/v1/courses/validate`, `/api/v1/imports/analyze`, `/api/v1/imports/jobs/{job_id}`, `/api/v1/imports/jobs/{job_id}/commit`, `/api/v1/media/upload`.
- Existing persistence and repository surfaces: `CourseRecord`, `PageRecord`, `ComponentRecord`, `TemplateRecord`, `TemplateDefinition`, `ImportJob`, `CourseRepository`, `PageRepository`, `ComponentRepository`, `TemplateRepository`, `ImportJobRepository`.
- Planned AI additions: `/api/v1/ai/*` routers, AI session persistence, proposal persistence, confirmation tokens, RAG index, document ingestion route, audit/outbox tables, AI telemetry, model routing.
- The requested `/api/v1/files/upload` document route is not implemented today; current package ingestion is `/api/v1/imports/analyze`, and media upload is `/api/v1/media/upload`.

### ⚠️ CRITICAL: Missing Auth/AuthZ/Multi-Tenancy Foundations

The current codebase has **NO** authentication, authorization, or multi-tenancy infrastructure:
- No JWT/OAuth/session authentication middleware (only CORS middleware in `app/main.py`)
- No user identity model — no `user_id`, `created_by`, or user context in any model or route
- No organization/tenant model — no `organization_id` in any database table
- No permission/role system — all routes are wide open

**All AI user stories depend on these foundations** for session scoping, proposal ownership, audit attribution, and tenant data isolation. See [PREREQUISITE_MOCK_STORIES.md](PREREQUISITE_MOCK_STORIES.md) for 5 prerequisite mock service stories (US-AI-PR01 through US-AI-PR05) that MUST be completed before any AI story begins. These provide mock/stub implementations with `# TODO(AUTH):`, `# TODO(AUTHZ):`, `# TODO(TENANT):`, `# TODO(SESSION):`, and `# TODO(USER):` markers where real services will be plugged in later.

## Canonical Dependency Order

| Order | Story | Primary dependency | Unlocks |
|---:|---|---|---|
| **PR1** | **US-AI-PR01 Mock Authentication Service** | None | User identity for ALL AI stories |
| **PR2** | **US-AI-PR02 Mock Authorization Service** | PR01 | Permission checks for ALL AI stories |
| **PR3** | **US-AI-PR03 Mock Multi-Tenancy Context** | PR01 | Tenant isolation for ALL AI stories |
| **PR4** | **US-AI-PR04 Mock Session Auth Middleware** | PR01, PR02, PR03 | AI session scoping |
| **PR5** | **US-AI-PR05 Mock User & Organization Resolver** | PR01, PR03 | User profiles, org settings |
| 1 | US-AI-001 Preserve manual authoring | PR01-PR05 | Safe AI rollout |
| 2 | US-AI-002 AI feature flags and model config | None (config-only, but routes use PR01) | Controlled enablement |
| 3 | US-AI-003 Isolated AI API module | US-AI-002 | All AI routes |
| 4 | US-AI-004 AI persistence foundations | US-AI-003, PR01, PR03 | Sessions, proposals, audit |
| 5 | US-AI-005 Tool and template contract registry | US-AI-003 | Tool calls, validation |
| 6 | US-AI-006 AI session creation | US-AI-004, US-AI-005, PR04 | Scoped tools |
| 7 | US-AI-007 Page list and fetch tools | US-AI-006, PR04 | Proposal context |
| 8 | US-AI-008 Course and page validation pipeline | US-AI-005, US-AI-007 | Proposal gating |
| 9 | US-AI-009 Generic proposal lifecycle | US-AI-004, US-AI-008 | Create/update/delete proposals |
| 10 | US-AI-010 Apply safety, audit, and outbox | US-AI-009 | Mutations |
| 11 | US-AI-011 Create page proposal and apply | US-AI-010 | AI page creation |
| 12 | US-AI-012 Update page proposal and apply | US-AI-010 | AI page edits |
| 13 | US-AI-013 Delete page proposal and confirm | US-AI-010 | Destructive delete scenario |
| 14 | US-AI-014 Simple chat edit orchestration | US-AI-007, US-AI-012 | Natural-language edit loop |
| 15 | US-AI-015 Similar course retrieval | US-AI-006 | RAG examples |
| 16 | US-AI-016 File upload and ingestion job foundation | US-AI-004 | Document import |
| 17 | US-AI-017 Document extraction and page-plan review | US-AI-016, US-AI-008 | Human-reviewed file import |
| 18 | US-AI-018 Validation report UI | US-AI-008 | Reviewer workflow |
| 19 | US-AI-019 Full course from uploaded file | US-AI-011, US-AI-017 | Batch course generation |
| 20 | US-AI-020 Admin audit and recovery | US-AI-010 | Compliance operations |
| 21 | US-AI-021 Observability, rate limits, and rollout gates | US-AI-002, US-AI-010 | Production operations |
| 22 | US-AI-022 End-to-end regression suite | US-AI-014, US-AI-019, US-AI-020 | Release readiness |
| 23 | US-AI-023 AI chat endpoint and LLM interaction loop | US-AI-006, US-AI-007 | All chat-driven flows |
| 24 | US-AI-024 Frontend AI integration layer | US-AI-006, US-AI-009 | User-facing AI features |
| 25 | US-AI-025 Prompt safety and content guardrails | US-AI-003 | Safe LLM interaction |
| 26 | US-AI-026 Multi-provider model routing and fallback | US-AI-002 | Resilient model access |
| 27 | US-AI-027 JSON repair and structured output recovery | US-AI-005, US-AI-026 | Robust LLM parsing |
| 28 | US-AI-028 Context pruning and token optimization | US-AI-005, US-AI-023 | Cost-efficient prompts |
| 29 | US-AI-029 Batch proposal and all-or-nothing semantics | US-AI-010 | Multi-page operations |
| 30 | US-AI-030 Course assembly into existing editor state | US-AI-011 | Editor integration |
| 31 | US-AI-031 RLHF feedback and provenance tracking | US-AI-010, US-AI-023 | Model improvement data |
| 32 | US-AI-032 Policy engine for auto-apply decisions | US-AI-009 | Risk-based automation |
| 33 | US-AI-033 Event-driven outbox and downstream consumers | US-AI-010 | Search, analytics, integrations |
| 34 | US-AI-034 Durable workflow engine for long-running AI jobs | US-AI-004, US-AI-023 | Async job reliability |
| 35 | US-AI-035 AI content accessibility compliance | US-AI-008 | WCAG-compliant AI output |
| 36 | US-AI-036 Cost tracking and token budget enforcement | US-AI-002, US-AI-026 | Financial governance |
| 37 | US-AI-037 Template definition harvesting from AI content | US-AI-011, US-AI-019 | Reusable AI templates |
| 38 | US-AI-038 SCORM export readiness for AI-generated content | US-AI-008, US-AI-030 | Export-compatible AI output |
| 39 | US-AI-039 Session context window recovery | US-AI-006, US-AI-023 | Session resilience |
| 40 | US-AI-040 AI content versioning and rollback | US-AI-010, US-AI-020 | Undo/redo for AI changes |
| 41 | US-AI-041 Async preview generation service | US-AI-009, US-AI-024 | Non-blocking previews |
| 42 | US-AI-042 System prompt versioning and A/B testing | US-AI-023, US-AI-031 | Prompt optimization |
| 43 | US-AI-043 Concurrency control and page locking | US-AI-010 | Safe concurrent AI edits |
| 44 | US-AI-044 Two-tier model architecture (Planner + Generator) | US-AI-026 | Cost-optimized model usage |
| 45 | US-AI-045 Real-time job status and notifications | US-AI-024, US-AI-034 | Live progress updates |
| 46 | US-AI-046 AI-assisted course-level operations | US-AI-011, US-AI-013 | Course create/delete via AI |
| 47 | US-AI-047 Multi-user collaboration on AI-authored content | US-AI-006, US-AI-043 | Team AI authoring |
| 48 | US-AI-048 Dead letter queue and failed job recovery | US-AI-034 | AI job resilience |
| 49 | US-AI-049 Confirmation token system | US-AI-004, US-AI-009 | Destructive operation safety |
| 50 | US-AI-050 Stale detection and merge resolution | US-AI-010, US-AI-043 | Concurrent edit resolution |

## User Stories

### US-AI-001 - Preserve Manual Authoring While Adding AI Entry Points

As an Author, I want the existing manual course editor to remain unchanged while AI is added as an optional path, so that current workflows are not disrupted.

- Source flows: All flows, cross-cutting.
- Priority: MUST.
- Depends on: None.
- Functional details:
  - Manual create, edit, validate, preview, and export workflows remain available.
  - AI entry points are additive, such as "Build with AI" and AI chat panel actions.
  - Users can switch from AI-generated content into the normal editor after apply.
- Technical details:
  - Do not refactor existing renderers or export pipeline as part of AI enablement.
  - AI backend code lives under isolated AI routers/services.
  - Existing routes remain backward-compatible.
- Acceptance criteria:
  - Existing page/component CRUD tests still pass with AI disabled.
  - AI feature can be hidden by configuration without affecting manual authoring.
  - Applied AI content is persisted in existing course/page/component structures.

### US-AI-002 - Configure AI Feature Flags, Models, and Provider Routing

As an Admin, I want configurable AI feature flags and model/provider settings, so that AI can be rolled out safely and adjusted without code changes.

- Source flows: Infrastructure for all AI flows.
- Priority: MUST.
- Depends on: None.
- Functional details:
  - Admins can enable or disable AI authoring by environment, tenant, or organization.
  - The platform supports an allowlist of models and a fallback model.
  - Unsupported model requests are rejected with clear errors.
- Technical details:
  - Add settings for `AI_AUTHORING_ENABLED`, primary model, fallback model, token budgets, retry counts, and timeout values.
  - Validate model IDs against an allowlist at request intake.
  - Preserve prompt/model/schema version metadata for audit.
- Acceptance criteria:
  - AI routes return disabled responses when the feature flag is off.
  - Provider timeouts can fall back to configured fallback behavior.
  - Configuration is validated at app startup or first AI service initialization.

### US-AI-003 - Create an Isolated AI API Module

As a Backend Engineer, I want AI routes and services isolated from existing course APIs, so that the AI feature remains an add-on layer.

- Source flows: All `/api/v1/ai/*` flows.
- Priority: MUST.
- Depends on: US-AI-002.
- Functional details:
  - Expose AI-specific session, chat, tool, proposal, and ingestion APIs.
  - Keep existing `/api/v1/courses/*`, `/api/v1/imports/*`, and `/api/v1/media/*` routes intact.
- Technical details:
  - Add routers such as `app/routers/ai_sessions.py`, `app/routers/ai_tools.py`, and `app/routers/ai_chat.py`.
  - Add service package such as `app/services/ai/`.
  - AI services call existing repositories instead of duplicating persistence logic.
- Acceptance criteria:
  - API docs show AI routes under separate tags.
  - Disabling AI router registration leaves existing backend behavior unchanged.
  - AI route error responses use the same structured error envelope style as current APIs.

### US-AI-004 - Add AI Persistence Foundations

As the System, I need durable records for sessions, proposals, confirmations, audit entries, and outbox events, so that AI workflows are recoverable and compliant.

- Source flows: 1, 3, 4, 5, 8, 9, 10, 11, 12.
- Priority: MUST.
- Depends on: US-AI-003.
- Functional details:
  - Sessions expire and are scoped to one user, organization, and course.
  - Proposals have lifecycle states and cannot be applied twice.
  - Destructive confirmations have separate tokens and expiry.
  - Audit and outbox records are written for every applied mutation.
- Technical details:
  - Add tables or equivalent persistence for `ai_sessions`, `ai_proposals`, `ai_confirmation_tokens`, `ai_audit_logs`, and `outbox_events`.
  - Store proposal `base_hash`, `operation`, `before_snapshot`, `after_candidate`, `validation_result`, `expires_at`, and `applied_at`.
  - Add repository/service abstraction for AI persistence.
- Acceptance criteria:
  - Expired sessions and proposals are rejected.
  - Proposal apply is idempotent when appropriate and blocked when already used.
  - Audit/outbox writes are transactionally coupled to successful mutations.

### US-AI-005 - Version Tool Schemas and Template Contracts

As an AI Platform Engineer, I want versioned tool schemas and template capability contracts, so that the model can only call supported operations with valid data.

- Source flows: 2, 3, 4, 5, 6, 7, 8, 12.
- Priority: MUST.
- Depends on: US-AI-003.
- Functional details:
  - The agent receives a strict tool allowlist.
  - AI-generated pages use only approved templates for MVP.
  - Tool contracts are stable, documented, and versioned.
- Technical details:
  - Use `TOOL_SCHEMAS_CLAUDE_NATIVE.md` as the initial schema source.
  - Build a runtime registry for `create_session`, `list_pages`, `fetch_page`, `propose_create_page`, `apply_page_proposal`, `propose_update_page`, `apply_update_proposal`, `propose_delete_page`, `confirm_delete_page`, `validate_course`, `query_similar_courses`, and `analyze_document_for_import`.
  - Bind template capabilities to existing `TemplateDefinition`, component registry, renderer manifest, and MVP template whitelist.
- Acceptance criteria:
  - Unsupported tool names are rejected server-side.
  - Unsupported template types are rejected before proposal creation.
  - Each proposal records tool schema version and template/schema version.

### US-AI-006 - Create Scoped AI Authoring Sessions

As an Author, I want to start an AI authoring session for one course, so that AI operations are scoped to the right course and permissions.

- Source flow: 1. AI Session Creation Flow.
- Priority: MUST.
- Depends on: US-AI-004, US-AI-005.
- Functional details:
  - User clicks "Build with AI" or opens AI chat from a course.
  - Backend returns `session_id`, expiry, permissions, and current course state summary.
  - Frontend stores the session while the AI panel is active.
- Technical details:
  - Implement `POST /api/v1/ai/sessions`, `GET /api/v1/ai/sessions/{session_id}`, and `DELETE /api/v1/ai/sessions/{session_id}`.
  - Validate authenticated user, organization, course existence, and course access.
  - Store immutable `course_id` in the session and reject cross-course tool calls.
- Acceptance criteria:
  - Session creation fails for unknown courses or unauthorized users.
  - Session response includes enough state for the AI UI to initialize.
  - Expired sessions cannot call tools.

### US-AI-007 - List and Fetch Course Pages for AI Context

As an AI Agent, I want read-only tools to list and fetch pages from the current course, so that proposals always use current database state.

- Source flow: 2. Page List and Fetch Flow.
- Priority: MUST.
- Depends on: US-AI-006.
- Functional details:
  - Agent can list page metadata for the session course.
  - Agent can fetch a full page with component data before editing.
  - The system blocks reads outside the session course.
- Technical details:
  - Implement AI tool adapters over existing `GET /api/v1/courses/{courseId}/pages` and `GET /api/v1/courses/{courseId}/pages/{pageId}`.
  - Use `PageRepository.list_by_course` and `PageRepository.get_by_course_and_page`.
  - Return `updatedAt` or a deterministic hash for staleness checks.
- Acceptance criteria:
  - `list_pages(session_id)` returns ordered metadata and total count.
  - `fetch_page(session_id, page_id)` returns full page/component data.
  - Missing, unauthorized, or stale-session requests return structured errors.

### US-AI-008 - Unify Course, Page, Schema, Export, and Accessibility Validation

As a Reviewer, I want server-side validation for AI-proposed or existing course content, so that invalid content cannot be applied or exported.

- Source flow: 6. Course Validation Flow.
- Priority: MUST.
- Depends on: US-AI-005, US-AI-007.
- Functional details:
  - Validate a full course, a page proposal, or a changed component set.
  - Return categorized errors and warnings with field paths.
  - Blocking errors stop proposal apply; warnings remain visible to the user.
- Technical details:
  - Reuse `/api/v1/courses/validate`, `Course` Pydantic model compatibility checks, component registry, `TemplateDefinition`, and `ExportValidator`.
  - Add proposal-specific validation for changed scope only.
  - Include SCORM/export readiness and accessibility hints where data is available.
- Acceptance criteria:
  - Invalid required fields return errors with field paths.
  - Unsupported component/template types are detected.
  - Validation output is stable enough for UI rendering and AI retry prompts.

### US-AI-009 - Implement Generic Proposal Lifecycle

As the System, I want every AI mutation to become a proposal first, so that AI cannot directly mutate course content.

- Source flow: 12. Propose, Validate, Confirm, Apply Safety Flow.
- Priority: MUST.
- Depends on: US-AI-004, US-AI-008.
- Functional details:
  - Proposals are created for create, update, delete, and batch import operations.
  - A proposal contains preview data, validation status, warnings, and changed fields.
  - Users can approve, reject, or request changes before apply.
- Technical details:
  - Implement proposal states such as `PENDING_REVIEW`, `APPROVED`, `APPLYING`, `APPLIED`, `REJECTED`, `EXPIRED`, `FAILED`.
  - Store base hashes to detect stale data.
  - Enforce proposal TTL and one-time apply semantics.
- Acceptance criteria:
  - No `propose_*` endpoint mutates `CourseRecord`, `PageRecord`, or `ComponentRecord`.
  - Applying an expired or stale proposal returns conflict or expired errors.
  - Proposal preview can be rendered by the frontend without another LLM call.

### US-AI-010 - Apply Proposals with Idempotency, Audit, and Outbox Events

As an Admin, I want applied AI changes to be transactional, auditable, and publishable to downstream systems, so that production changes are safe and traceable.

- Source flow: 12. Propose, Validate, Confirm, Apply Safety Flow.
- Priority: MUST.
- Depends on: US-AI-009.
- Functional details:
  - Apply only runs after explicit user confirmation.
  - Apply rechecks ownership, TTL, base hash, and validation.
  - Successful mutations produce audit and outbox records.
- Technical details:
  - Use database transactions for proposal state update, domain mutation, audit write, and outbox write.
  - Support idempotency keys for safe retries.
  - Write event types such as `PageCreatedByAI`, `PageUpdatedByAI`, `PageDeletedByAI`, `CourseCreatedFromFile`.
- Acceptance criteria:
  - Double-submit of an idempotent apply does not create duplicate pages.
  - Failed post-apply validation rolls back the mutation.
  - Audit record includes user, session, proposal, operation, before/after, and schema/model metadata.

### US-AI-011 - Propose and Apply AI-Created Pages

As an Author, I want AI to propose a new page using approved templates and then apply it after I approve, so that I can quickly build course content.

- Source flow: 3. Create Page Proposal and Apply Flow.
- Priority: MUST.
- Depends on: US-AI-010.
- Functional details:
  - Author asks AI to add a page.
  - Backend validates title, template type, page data, components, and order.
  - Frontend shows a preview before apply.
  - Approved proposal creates the page in the existing course.
- Technical details:
  - Implement `propose_create_page(session_id, title, template_type, data)` and `apply_page_proposal(proposal_id, user_confirmed=true)`.
  - Persist through `PageRepository.create` and `ComponentRepository.create` where component payloads exist.
  - Reuse existing `POST /api/v1/courses/{courseId}/pages` semantics where possible.
- Acceptance criteria:
  - Unsupported templates are rejected before proposal creation.
  - Apply creates exactly one page for one proposal.
  - Response returns new `pageId`, order, page payload, and refreshed course state.

### US-AI-012 - Propose and Apply AI Updates to Existing Pages

As an Author, I want AI to propose changes to an existing page and apply them only after I approve a diff, so that targeted edits remain controlled.

- Source flow: 4. Update Page Proposal and Apply Flow.
- Priority: MUST.
- Depends on: US-AI-010.
- Functional details:
  - AI fetches the latest page before proposing updates.
  - The proposal shows before/after diff and validation messages.
  - Apply updates only approved fields.
- Technical details:
  - Implement `propose_update_page(session_id, page_id, patch)` and `apply_update_proposal(session_id, proposal_id, user_confirmed=true)`.
  - Patch scope should allow safe fields such as title, layout, theme, page completion, and components.
  - Apply through `PageRepository.update` and `ComponentRepository` as needed.
- Acceptance criteria:
  - A stale base hash returns a 409 conflict on apply.
  - The diff lists changed fields.
  - Out-of-scope fields such as `course_id` or foreign `page_id` are rejected.

### US-AI-013 - Propose and Confirm Destructive Page Deletes

As an Author, I want AI to request explicit confirmation before deleting a page, so that destructive operations cannot happen accidentally.

- Source flows: 5. Delete Page Proposal and Confirm Flow; 11. Destructive Delete Scenario Flow.
- Priority: MUST.
- Depends on: US-AI-010.
- Functional details:
  - AI can propose deletion but cannot delete immediately.
  - Frontend shows a destructive confirmation modal with page title and warnings.
  - User must explicitly approve before deletion.
- Technical details:
  - Implement `propose_delete_page(session_id, page_id)` and `confirm_delete_page(session_id, proposal_id, user_approved_delete=true)`.
  - Generate confirmation token bound to session, proposal, page hash, and expiry.
  - Use existing `DELETE /api/v1/courses/{courseId}/pages/{pageId}` behavior through `PageRepository.delete`.
  - Check navigation, scoring, branching, final assessment, and export dependencies before apply.
- Acceptance criteria:
  - Delete proposals always return `confirmation_required=true`.
  - Delete apply fails without explicit user approval.
  - Audit includes deleted page snapshot and confirmation token identifier.

### US-AI-014 - Support Simple Chat Edit Scenario

As an Author, I want to ask the AI in chat to refine a page, so that I can make natural-language edits without manually locating every field.

- Source flow: 9. Simple Chat Edit Scenario Flow.
- Priority: MUST.
- Depends on: US-AI-007, US-AI-012.
- Functional details:
  - User sends a chat instruction such as "simplify this page" or "make the intro more concise".
  - Agent lists/fetches pages, resolves the target, proposes an update, and waits for approval.
  - Ambiguous targets trigger clarification instead of guessing.
- Technical details:
  - Implement `POST /api/v1/ai/chat`.
  - Chat orchestrator uses only registered tools and never calls direct mutation routes.
  - Store chat turn ID, model metadata, selected page context, tool calls, and proposal ID.
- Acceptance criteria:
  - Chat edit creates an update proposal, not a direct DB update.
  - Ambiguous page references return a clarification prompt.
  - Approved chat update refreshes the editor with the latest DB state.

### US-AI-015 - Retrieve Similar Courses for Examples and Tone

As an AI Agent, I want similar course examples and tone guidance, so that generated content can match proven pedagogy without using RAG as an authority for contracts.

- Source flow: 7. Similar Course Retrieval Flow.
- Priority: SHOULD.
- Depends on: US-AI-006.
- Functional details:
  - Agent can request similar course examples by query and filters.
  - Results include safe excerpts, template examples, tone notes, and relevance scores.
  - Empty results are non-fatal.
- Technical details:
  - Implement `query_similar_courses(session_id, query, filters)`.
  - Add org-scoped vector index when available; fall back to keyword/search over existing courses/templates if not.
  - Redact private data and enforce tenant isolation.
  - Do not source API contracts, validation rules, or schemas from RAG.
- Acceptance criteria:
  - Cross-tenant content is never returned.
  - Result snippets are bounded and safe for prompt inclusion.
  - Empty retrieval returns guidance that generation may continue without RAG.

### US-AI-016 - Add File Upload and Ingestion Job Foundation for AI

As an Author, I want to upload source documents for AI analysis, so that course generation can begin from existing material.

- Source flows: 8 and 10.
- Priority: MUST for file-import MVP.
- Depends on: US-AI-004.
- Functional details:
  - User uploads PDF, DOCX, or supported packages.
  - Backend creates a job and returns status for polling.
  - The UI can show progress, warnings, and errors.
- Technical details:
  - Add planned document route such as `/api/v1/files/upload` or `/api/v1/ai/ingestions`.
  - Reuse current `/api/v1/imports/analyze`, `/api/v1/imports/jobs/{job_id}`, and `ImportJobRepository` for SCORM/package ingestion.
  - Enforce file size, file type, storage path safety, content sniffing, and malware scanning policy.
- Acceptance criteria:
  - Unsupported file types are rejected.
  - Upload creates a durable job record with `job_id`, status, progress, and source metadata.
  - Job status can be polled by the frontend.

### US-AI-017 - Extract Documents and Review Proposed Page Breakdown

As an Author, I want the system to extract a document and propose a page breakdown for review, so that I can control course structure before AI generates content.

- Source flow: 8. File Ingestion / Document Import Flow.
- Priority: MUST for file-import MVP.
- Depends on: US-AI-016, US-AI-008.
- Functional details:
  - Deterministic extractor parses sections, headings, tables, and media references.
  - LLM segmenter maps extracted sections to approved templates.
  - User can merge, split, reorder, retitle, or change template suggestions before approving.
- Technical details:
  - Add PDF and DOCX extractors; current SCORM path uses `ImportService`, `StrategyRegistry`, `SchemaInferenceEngine`, and `AssetRewriter`.
  - Store source indices and extraction warnings on the job.
  - Validate source coverage, page count, template whitelist, and unsupported structures.
- Acceptance criteria:
  - Extracted sections have stable source references.
  - Proposed pages include title, suggested template, source indices, and rationale.
  - No pages are created before user approves the breakdown.

### US-AI-018 - Display Course Validation Reports to Authors and Reviewers

As a Reviewer, I want a validation report linked to affected pages/components, so that I can quickly resolve issues before apply or export.

- Source flow: 6. Course Validation Flow.
- Priority: SHOULD.
- Depends on: US-AI-008.
- Functional details:
  - UI shows errors, warnings, severity, affected field, and remediation hints.
  - Authors can jump from a validation issue to the related page or component.
  - Proposal review surfaces validation messages before approval.
- Technical details:
  - Render response from `/api/v1/courses/validate` and AI validation adapters.
  - Normalize field paths across legacy templates and component pages.
  - Include validation timestamp and schema versions.
- Acceptance criteria:
  - Blocking errors are visually distinct from warnings.
  - Proposal apply button is disabled when blocking errors exist.
  - Validation report can be refreshed after manual edits.

### US-AI-019 - Generate a Full Course From an Uploaded File

As an Author, I want to turn an approved uploaded-file page plan into a complete course draft, so that I can start from source material and finish in the existing editor.

- Source flow: 10. Full Course from Uploaded File Scenario Flow.
- Priority: SHOULD after page proposal MVP.
- Depends on: US-AI-011, US-AI-017.
- Functional details:
  - User approves page plan.
  - AI generates page/component data for each approved page.
  - Backend validates all pages and shows a final course preview.
  - User confirms and the system applies the batch all-or-nothing.
- Technical details:
  - Use batch proposal semantics with one proposal batch tied to the upload job.
  - Apply through `CourseRepository`, `PageRepository`, `ComponentRepository`, and for current SCORM imports, `ImportService.commit_import`.
  - Harvest reusable template definitions through current template-type dedupe when applicable.
- Acceptance criteria:
  - If any page fails validation, no pages are applied.
  - Final apply returns the created or updated course with pages.
  - Audit includes file hash, source type, pages created, validation summary, and job ID.

### US-AI-020 - Provide Admin Audit, Compliance, and Recovery Views

As an Admin, I want to inspect AI operations and recover from problematic changes, so that AI-assisted authoring meets governance requirements.

- Source flows: 3, 4, 5, 9, 10, 11, 12.
- Priority: SHOULD for production rollout, MUST for regulated tenants.
- Depends on: US-AI-010.
- Functional details:
  - Admin can filter audit logs by user, course, operation, proposal, model, date range, or outcome.
  - Admin can inspect before/after snapshots and validation summaries.
  - Recovery guidance is available for applied changes.
- Technical details:
  - Expose read-only audit endpoints over `ai_audit_logs`.
  - Link audit records to outbox events, proposal records, and course/page IDs.
  - If rollback is supported, generate rollback proposals instead of direct rollback mutation.
- Acceptance criteria:
  - Every applied AI mutation is queryable in audit.
  - Audit details do not expose secrets or private prompt data beyond approved metadata.
  - Admin can identify exactly which proposal changed which page.

### US-AI-021 - Add Production Observability, Rate Limits, and Rollout Gates

As an Operator, I want operational controls and telemetry around AI usage, so that cost, latency, and failure modes are visible and bounded.

- Source flows: All flows, cross-cutting.
- Priority: MUST for production.
- Depends on: US-AI-002, US-AI-010.
- Functional details:
  - Operators can see AI request volume, tool failures, validation failures, token usage, latency, and provider errors.
  - Rate limits and quotas protect tenants and providers.
  - Rollout can be limited by environment, tenant, role, or route.
- Technical details:
  - Add trace IDs across chat, tool calls, proposal, apply, validation, and outbox.
  - Emit metrics for model calls, tool calls, retry counts, validation categories, and apply outcomes.
  - Enforce per-user, per-tenant, and per-session rate limits.
- Acceptance criteria:
  - Every AI response includes or logs a trace ID.
  - Quota exceeded returns 429 with retry guidance.
  - Dashboards or logs can distinguish model failure, validation failure, and apply conflict.

### US-AI-022 - Build End-to-End Regression and Release Readiness Tests

As a QA Engineer, I want automated coverage for the full AI authoring path, so that releases do not break safety, validation, or persistence guarantees.

- Source flows: All flows.
- Priority: MUST before production launch.
- Depends on: US-AI-014, US-AI-019, US-AI-020.
- Functional details:
  - Tests cover session creation, read tools, create/update/delete proposals, validation, chat edit, file import, and audit.
  - Tests verify manual authoring still works with AI enabled and disabled.
  - Tests cover expired/stale proposals, permission failures, validation failures, and duplicate apply attempts.
- Technical details:
  - Add API tests for AI routers and repository/service tests for proposal lifecycle.
  - Add E2E tests for frontend proposal review and destructive confirmation.
  - Mock model provider calls with deterministic tool-call outputs.
- Acceptance criteria:
  - CI can run without real model provider credentials.
  - Safety invariant tests prove `propose_*` never mutates domain data.
  - Release checklist includes feature flag, migration, audit, rollback, and observability verification.

### US-AI-023 - Implement AI Chat Endpoint and LLM Interaction Loop

As an Author, I want a dedicated AI chat endpoint that orchestrates the LLM interaction loop, so that the model can call tools, receive results, and produce final responses in a managed conversation.

- Source flow: 14. AI Chat Orchestration and LLM Interaction Loop.
- Priority: MUST.
- Depends on: US-AI-006, US-AI-007.
- Functional details:
  - The chat endpoint accepts a user prompt with optional page context and returns assistant messages with embedded proposals.
  - The orchestrator maintains the tool-calling loop: system prompt → user message → LLM response → tool calls → tool results → LLM response → final output.
  - Tool call results are validated and any errors are fed back to the LLM for retry within configured limits.
  - The chat response includes session state summary, tool call trace, and any proposals created during the turn.
- Technical details:
  - Implement `POST /api/v1/ai/chat` accepting `{session_id, course_id, prompt, mode, selected_context}`.
  - Build an AI chat orchestrator in `app/services/ai/chat_orchestrator.py` that manages the tool-calling loop, error retry, and response streaming.
  - Load and inject the system prompt from a versioned source with template, tool, and rule documentation.
  - Track `chat_turn_id`, `model_used`, `prompt_version`, `tool_calls_made`, `proposal_ids_created`, and `trace_id` for each turn.
  - Enforce a configurable max tool-call round-trip limit per chat turn (default 10).
- Acceptance criteria:
  - A single chat turn can produce multiple tool calls before returning a final message.
  - Tool call errors are fed back to the LLM for self-correction within the same turn.
  - Chat turn metadata is persisted for audit and debugging.
  - Chat endpoint rejects requests without a valid active session.

### US-AI-024 - Build Frontend AI Integration Layer

As a Frontend Engineer, I want a dedicated AI integration layer in the frontend with session management, proposal rendering, and confirmation UI, so that users have a consistent AI authoring experience.

- Source flow: 17. Frontend AI Integration Layer.
- Priority: MUST.
- Depends on: US-AI-006, US-AI-009.
- Functional details:
  - Frontend stores and manages AI session lifecycle (create, refresh, expire, end).
  - All AI API calls include the session authorization header.
  - Proposal previews are rendered with field-level diffs and validation messages.
  - Destructive operations show explicit confirmation modals.
  - File ingestion includes upload progress, extraction preview, and page-plan review UI.
- Technical details:
  - Implement `src/ai/` module with `AISessionContext`, API client, proposal review components, and confirmation modals.
  - Store `sessionId` in sessionStorage; refresh on page reload via `GET /api/v1/ai/sessions/{sessionId}`.
  - Render proposal diffs as before/after comparison with changed field highlighting.
  - Build an upload review workflow: preview sections, merge/split/reorder pages, confirm breakdown.
- Acceptance criteria:
  - AI button is visible only when feature flag is enabled and session is active.
  - Expired sessions redirect users to restart AI mode with a clear message.
  - Proposal diff shows changed fields distinctly from unchanged fields.
  - Destructive confirmation modal requires explicit user action and cannot be dismissed accidentally.
  - Manual authoring UI is unchanged when AI feature flag is disabled.

### US-AI-025 - Add Prompt Safety and Content Guardrails

As a Platform Operator, I want prompt injection detection, PII scanning, and output safety checks before LLM interaction, so that malicious or sensitive content is blocked before it reaches the model or the user.

- Source flow: 15. Prompt Safety and Content Guardrails.
- Priority: MUST for production.
- Depends on: US-AI-003.
- Functional details:
  - Incoming user prompts are scanned for PII patterns, prompt injection attempts, and policy violations before being sent to the LLM.
  - LLM outputs are scanned for toxicity, brand safety, and disallowed content before being returned to the user.
  - Blocked prompts return clear policy-violation errors; blocked outputs are replaced with safe fallback messages.
- Technical details:
  - Implement `app/services/ai/prompt_guard.py` with PII regex/entity detection and injection pattern matching.
  - Implement `app/services/ai/output_guard.py` with toxicity scoring, keyword blocklists, and content policy rules.
  - Redact or reject prompts containing emails, phone numbers, credentials, or known injection patterns.
  - Log safety events with severity, rule triggered, and sanitized context for security review.
- Acceptance criteria:
  - Prompt containing `ignore previous instructions` patterns is rejected with a safety error.
  - Prompt containing an email address is redacted before reaching the LLM.
  - LLM output containing blocked terms is replaced with a policy-compliance message.
  - Safety events are logged and queryable by security operations.

### US-AI-026 - Implement Multi-Provider Model Routing and Fallback

As an Operator, I want the AI layer to route requests across multiple LLM providers with automatic fallback, so that availability and cost are optimized without user impact.

- Source flow: 13. Platform Runtime and Operations Flow.
- Priority: SHOULD for MVP, MUST for production.
- Depends on: US-AI-002.
- Functional details:
  - Primary model is tried first; on timeout, rate limit, or server error, the fallback model is used automatically.
  - Different task types can route to different models (e.g., fast/cheap for planning, premium for generation).
  - Fallback events are logged with reason, latency impact, and model used.
- Technical details:
  - Implement `app/services/ai/model_router.py` with primary/fallback chain and per-task routing rules.
  - Configure model tiers: planner (fast/cheap), generator (premium), repair (fast), safety (deterministic).
  - Add circuit breaker for each provider: after N consecutive failures, skip provider for cooldown period.
  - Track per-model latency, error rate, and cost in telemetry.
- Acceptance criteria:
  - When primary model returns a 5xx error, the fallback model is used and the user sees no difference.
  - Both models failing returns a clear "AI service unavailable" message.
  - Model routing metadata is included in audit and telemetry records.
  - Circuit breaker prevents cascading retries to a failing provider.

### US-AI-027 - Add JSON Repair and Structured Output Recovery

As an AI Platform Engineer, I want malformed JSON from the LLM to be automatically repaired before rejection, so that minor formatting errors do not block the user's workflow.

- Source flow: 16. JSON Repair and Structured Output Recovery.
- Priority: SHOULD for MVP, MUST for production quality.
- Depends on: US-AI-005, US-AI-026.
- Functional details:
  - When the LLM returns invalid JSON for a tool call or structured output, a fast repair model attempts to fix it.
  - Common fixes include: trailing commas, unescaped quotes, missing braces, and comment removal.
  - If repair fails after configured attempts, the error is returned to the primary LLM for regeneration.
- Technical details:
  - Implement `app/services/ai/json_repair.py` with regex-based fixes and fallback to fast-model repair.
  - Configure max repair attempts per output (default 2) before escalating to regeneration.
  - Log repair events with original error, repair strategy used, and success/failure for quality monitoring.
  - Track repair frequency by template type to identify schema documentation gaps.
- Acceptance criteria:
  - JSON with trailing commas is repaired and processed without user-visible error.
  - JSON missing a closing brace is repaired within one repair attempt.
  - Unrepairable JSON returns a clear error to the LLM for regeneration with the specific failure reason.
  - Repair events do not count toward the user's tool-call rate limit.

### US-AI-028 - Implement Context Pruning and Token Optimization

As an Operator, I want the AI orchestrator to prune unused template schemas and context from prompts, so that token costs are minimized without degrading output quality.

- Source flow: 13. Platform Runtime and Operations Flow.
- Priority: SHOULD for production.
- Depends on: US-AI-005, US-AI-023.
- Functional details:
  - Before building a prompt, the orchestrator identifies which templates and tools are relevant to the current task.
  - Unused template schemas, tool definitions, and verbose context are pruned from the system prompt.
  - The pruner logs token savings per request for cost analysis.
- Technical details:
  - Implement `app/services/ai/context_pruner.py` that selects relevant template schemas and tool definitions based on the user's intent and course context.
  - Categorize system prompt sections as "always-include" (safety rules, core instructions), "contextual" (template schemas, tool details), and "droppable" (examples, verbose documentation).
  - Track tokens saved vs. total possible per request.
- Acceptance criteria:
  - A chat request targeting only text-content pages prunes assessment, tabs, and accordion schemas from the context.
  - Pruned prompts produce equivalent-quality output to full prompts for single-template tasks.
  - Token savings are logged and reported in cost dashboards.

### US-AI-029 - Support Batch Proposal Operations with All-or-Nothing Semantics

As an Author, I want to propose changes across multiple pages in one batch, so that file ingestion and bulk edits are atomic and previewable as a group.

- Source flow: 13 (Platform Runtime), 19. Batch Proposal and All-or-Nothing Semantics.
- Priority: SHOULD for MVP, MUST for file-import MVP.
- Depends on: US-AI-010.
- Functional details:
  - A batch proposal contains multiple page-level proposals with a shared batch ID and all-or-nothing contract.
  - If any page in the batch fails validation, the entire batch is rejected with per-page error details.
  - The user can fix failing pages and resubmit, or proceed without them.
- Technical details:
  - Implement `propose_batch_pages(session_id, pages[])` returning `batch_id`, per-page proposal IDs, and aggregated validation status.
  - Implement `apply_batch_proposals(session_id, batch_id, user_confirmed=true)` with transactional all-or-nothing apply.
  - Batch apply uses a single database transaction spanning all pages in the batch.
  - Store batch metadata including source (chat, file import), page count, and validation summary.
- Acceptance criteria:
  - If any page in a 5-page batch fails validation, no pages are created.
  - Batch preview shows per-page status (valid/warning/error) before apply.
  - User can remove a failing page from the batch and apply the remainder.
  - Batch audit record includes the batch ID, page count, and per-page proposal IDs.

### US-AI-030 - Assemble AI-Generated Content into Existing Editor State

As an Author, I want AI-generated courses and pages to load into the existing course editor, so that I can continue editing manually after AI generation completes.

- Source flow: 18. Course Assembly into Existing Editor.
- Priority: MUST.
- Depends on: US-AI-011.
- Functional details:
  - After AI creates or updates pages, the existing editor receives the refreshed course state and renders it identically to manually-authored content.
  - AI-generated pages use the same page/component data model as manual pages.
  - The editor can switch seamlessly between AI-generated and manually-authored pages within the same course.
- Technical details:
  - Reuse existing `CourseRecord`, `PageRecord`, and `ComponentRecord` persistence so AI output is native to the editor.
  - Implement `app/services/ai/course_assembler.py` to transform proposal output into the editor's expected state shape.
  - Ensure the editor's page list, preview, and export views work without modification on AI-generated content.
- Acceptance criteria:
  - AI-generated pages appear in the course page list with correct order and metadata.
  - Clicking an AI-generated page opens it in the existing page editor with all fields editable.
  - Preview renders AI-generated and manual pages identically.
  - Editor undo/redo works across AI-generated pages.

### US-AI-031 - Collect RLHF Feedback and Track Provenance Metadata

As an AI Platform Engineer, I want to collect human feedback on AI outputs and track full provenance metadata, so that model performance can be measured and improved over time.

- Source flow: 20. RLHF Feedback and Provenance Tracking.
- Priority: SHOULD for production.
- Depends on: US-AI-010, US-AI-023.
- Functional details:
  - Every AI-generated page or component tracks its provenance: prompt version, model version, source documents, RAG chunks used, and generation timestamp.
  - When a user edits AI-generated content before applying, the edit distance and changed fields are captured as implicit feedback.
  - Explicit feedback (thumbs up/down, ratings) is captured from the chat UI.
- Technical details:
  - Add `provenance` JSON field to proposals and applied pages containing `{prompt_version, model_id, provider, source_doc_hash, rag_chunk_ids, generated_at}`.
  - Implement `app/services/ai/feedback_store.py` to record `{proposal_id, generated_json, final_json, edit_distance, changed_fields, explicit_rating, timestamp}`.
  - Store feedback in a dedicated table for offline analysis; do not block the user on feedback writes.
  - Compute aggregate metrics: acceptance rate, mean edit distance, approval rate by template type.
- Acceptance criteria:
  - Every applied AI page has provenance metadata queryable via audit.
  - User modifications to AI proposals before apply are captured as feedback events.
  - Feedback store is non-blocking: write failures do not affect the user's apply flow.
  - Aggregate metrics dashboard shows acceptance rate trends by template and model.

### US-AI-032 - Implement Policy Engine for Risk-Based Auto-Apply Decisions

As an Admin, I want a policy engine that determines when AI proposals can be auto-applied based on risk level, user role, and operation type, so that low-risk changes do not require manual review.

- Source flow: 21. Policy Engine for Auto-Apply Decisions.
- Priority: COULD for MVP, SHOULD for production efficiency.
- Depends on: US-AI-009.
- Functional details:
  - Low-risk operations (e.g., typo fixes, content-only updates to text-content pages) may be auto-applied for trusted roles.
  - High-risk operations (deletes, assessment changes, multi-page batches) always require explicit confirmation.
  - Policy rules are configurable by tenant and can be overridden by admins.
- Technical details:
  - Implement `app/services/ai/policy_engine.py` with risk scoring per operation type, template type, and change scope.
  - Define policy rules: `auto_apply` (no confirmation needed), `soft_confirm` (show preview, one-click approve), `hard_confirm` (modal with explicit action), `block` (requires admin override).
  - Store policy configuration per organization with tenant-specific overrides.
  - Log every policy decision with the rule evaluated, risk score, and outcome.
- Acceptance criteria:
  - A typo fix on a text-content page by an instructor is auto-applied without confirmation.
  - A delete-page proposal always requires hard confirmation regardless of user role.
  - Policy changes take effect immediately without server restart.
  - Policy decision audit log is queryable by admin.

### US-AI-033 - Implement Event-Driven Outbox for Downstream Consumers

As an Architect, I want AI mutations to emit versioned outbox events transactionally, so that search indexing, analytics, and external integrations can consume AI-authored content changes reliably.

- Source flow: 13. Platform Runtime and Operations Flow.
- Priority: SHOULD for production, MUST for regulated tenants.
- Depends on: US-AI-010.
- Functional details:
  - Every applied AI mutation writes an outbox event in the same database transaction.
  - Events are versioned, typed, and include enough payload for consumers to act without calling back.
  - Downstream consumers (search indexer, analytics pipeline, audit archive) process events at their own pace.
- Technical details:
  - Add `outbox_events` table with columns: `id`, `event_type`, `event_version`, `aggregate_id`, `payload`, `occurred_at`, `published_at`.
  - Write events synchronously in the apply transaction for types: `PageCreatedByAI`, `PageUpdatedByAI`, `PageDeletedByAI`, `CourseCreatedFromFile`, `BatchProposalApplied`, `TemplateDefinitionHarvested`.
  - Implement a lightweight outbox publisher (polling or LISTEN/NOTIFY) to forward events to a message broker or webhook.
  - Ensure at-least-once delivery semantics with idempotent consumers.
- Acceptance criteria:
  - Outbox event is written atomically with the domain mutation; a rollback removes the event.
  - Events include `trace_id` linking back to the AI session and proposal.
  - Outbox publisher can be disabled via configuration without affecting mutation apply.
  - Replaying outbox events does not duplicate downstream effects.

### US-AI-034 - Add Durable Workflow Engine for Long-Running AI Jobs

As an Operator, I want long-running AI jobs (file ingestion, batch course generation) to execute on a durable workflow engine with retry, checkpointing, and human-in-the-loop support, so that jobs survive restarts and failures.

- Source flow: 22. Durable Workflow Engine for Long-Running Jobs.
- Priority: COULD for MVP, SHOULD for production scale.
- Depends on: US-AI-004, US-AI-023.
- Functional details:
  - File ingestion and batch generation jobs are enqueued as workflows with defined phases.
  - Workflow state is durably checkpointed after each phase so progress is not lost on worker restart.
  - Human-in-the-loop steps (page plan approval, final course review) pause the workflow until the user responds.
  - Failed phases are retried with exponential backoff up to a configured max.
- Technical details:
  - Implement workflow abstraction in `app/services/ai/workflow_engine.py` with pluggable backend (in-process state machine for MVP, Temporal/Cadence for production).
  - Define workflow types: `FileIngestionWorkflow` (extract → segment → review → generate → validate → apply), `BatchGenerationWorkflow` (plan → generate → validate → review → apply).
  - Store workflow state in `ai_workflow_runs` table with `status`, `current_phase`, `checkpoint_data`, `retry_count`, and `next_run_at`.
  - Expose `GET /api/v1/ai/workflows/{workflow_id}` for status polling and `POST /api/v1/ai/workflows/{workflow_id}/signal` for human-in-the-loop responses.
- Acceptance criteria:
  - A file ingestion workflow survives backend restart and resumes from the last completed phase.
  - Workflow status is pollable by the frontend with phase-level progress.
  - Human-in-the-loop steps time out after a configurable period and the workflow is marked `EXPIRED`.
  - Failed workflows can be retried from the failed phase by an admin.

### US-AI-035 - Ensure AI-Generated Content Meets Accessibility Standards

As a Compliance Officer, I want AI-generated course content to be validated against WCAG 2.1 AA accessibility standards before apply, so that AI does not introduce accessibility regressions.

- Source flow: 23. AI Content Accessibility Compliance.
- Priority: SHOULD for MVP, MUST for regulated tenants.
- Depends on: US-AI-008.
- Functional details:
  - AI-generated pages are checked for: descriptive titles, alt text on images, sufficient color contrast hints, heading hierarchy, and accessible interaction patterns.
  - Accessibility violations are returned as warnings (not blocking errors) with specific remediation hints.
  - The LLM receives accessibility guidance in the system prompt to produce compliant content initially.
- Technical details:
  - Extend the validation pipeline in `app/services/ai/accessibility_validator.py` with template-specific WCAG checks.
  - Check: image components have alt text, assessment instructions are screen-reader compatible, tab/accordion structures have proper ARIA hints, color references include contrast notes.
  - Include accessibility score in proposal preview so reviewers can assess compliance before apply.
  - Track accessibility score trends over time to measure AI improvement.
- Acceptance criteria:
  - An AI-generated page with an image missing alt text receives a warning with the specific field and remediation hint.
  - Accessibility warnings do not block apply but are visible in the proposal review UI.
  - The system prompt instructs the LLM to include alt text, descriptive titles, and accessible structure.
  - Accessibility scores are tracked per template type and model version.

### US-AI-036 - Enforce Cost Tracking and Token Budget Limits

As an Admin, I want per-tenant and per-user token budget enforcement with cost tracking, so that AI usage stays within allocated financial limits.

- Source flow: 24. Cost Tracking and Token Budget Enforcement.
- Priority: SHOULD for MVP, MUST for production.
- Depends on: US-AI-002, US-AI-026.
- Functional details:
  - Each AI request is metered: input tokens, output tokens, model used, and computed cost.
  - Per-tenant monthly cost caps and per-user daily token limits are enforced.
  - Approaching or exceeding limits triggers warnings and eventual request blocking with clear messaging.
- Technical details:
  - Implement `app/services/ai/cost_tracker.py` with token counting (from API response metadata), cost calculation per model pricing, and budget enforcement.
  - Add configuration for `AI_TENANT_MONTHLY_COST_CAP_USD` and `AI_USER_DAILY_TOKEN_LIMIT`.
  - Store usage aggregates in `ai_usage_records` table partitioned by tenant, user, and date.
  - Expose `GET /api/v1/ai/usage` with current period usage, limit, and remaining budget.
- Acceptance criteria:
  - A user exceeding their daily token limit receives a 429 response with reset time.
  - A tenant approaching 80% of monthly cost cap triggers a warning notification to admins.
  - Every AI request logs token counts and computed cost for billing reconciliation.
  - Cost data is queryable by tenant, user, model, and date range.

### US-AI-037 - Harvest Reusable Template Definitions from AI-Generated Content

As a Course Designer, I want AI-generated pages with novel patterns to be harvestable as reusable template definitions, so that good AI outputs become available for manual authoring and future AI generation.

- Source flow: 25. Template Definition Harvesting.
- Priority: COULD for MVP.
- Depends on: US-AI-011, US-AI-019.
- Functional details:
  - After AI creates pages, the system identifies component patterns that match existing template types with high similarity.
  - Pages with unique, high-quality structures can be promoted to template definitions by an admin or course designer.
  - Harvested templates are added to the template registry and become available for both AI and manual authoring.
- Technical details:
  - Implement `app/services/ai/template_harvester.py` that computes signature hashes of AI-generated component data structures and compares against existing `TemplateDefinition` signatures.
  - Flag near-matches (same template type, similar but not identical schema) for admin review.
  - Promote-to-template creates a `TemplateDefinition` record with the AI component data as the example and inferred schema.
  - Track provenance: harvested template records its source AI session, proposal, and model version.
- Acceptance criteria:
  - AI-generated pages with novel component structures appear in an admin review queue.
  - Admin can preview, edit, and publish a harvested template definition.
  - Published harvested templates appear in the allowed-templates list for future AI sessions.
  - Harvested template provenance links back to the originating AI session and course.

### US-AI-038 - Validate AI-Generated Content for SCORM Export Readiness

As an Author, I want AI-generated courses to be validated for SCORM export compatibility before apply, so that AI-authored content exports as reliably as manually-authored content.

- Source flow: 26. SCORM Export Readiness for AI Content.
- Priority: SHOULD for production.
- Depends on: US-AI-008, US-AI-030.
- Functional details:
  - AI-generated pages are checked against SCORM export requirements: supported component types, valid scoring configurations, complete metadata, and exportable asset references.
  - Export-blocking issues are returned as errors in the proposal validation.
  - The LLM receives export compatibility guidance in the system prompt.
- Technical details:
  - Extend validation pipeline to call `ExportValidator` and `RendererManifest` checks on AI-proposed content.
  - Validate: all component types are in the renderer manifest as exportable, assessment scoring is within SCORM limits, media references resolve to exportable assets.
  - Include export readiness status in proposal preview alongside schema and business rule validation.
- Acceptance criteria:
  - An AI-proposed page using an unsupported component type receives a blocking validation error.
  - A final-assessment with a passing score outside 0-100 receives an export warning.
  - Export validation results appear in the proposal review UI alongside other validation messages.

### US-AI-039 - Handle Session Context Window Recovery

As an Author, I want the AI session to recover gracefully when the LLM context window truncates mid-session, so that I can continue working without losing course state or restarting from scratch.

- Source flow: 27. Session Context Window Recovery.
- Priority: SHOULD for production.
- Depends on: US-AI-006, US-AI-023.
- Functional details:
  - When the LLM context window is exhausted, the orchestrator detects truncation and reinitializes with a fresh system prompt and current database state.
  - The user sees a message that context was refreshed, and the AI retains access to all prior proposals and the current course state via tool calls.
  - No data is lost because the database remains the source of truth.
- Technical details:
  - Track approximate token usage per session and detect when approaching context limit (e.g., 80% of model max).
  - Implement context refresh: discard conversation history, reload system prompt, inject session summary (active proposals, course metadata), and instruct LLM to re-fetch state via tools.
  - Store session-level context summary in `ai_sessions` table for fast rehydration: `{course_id, active_proposal_ids, last_page_focused, key_decisions}`.
  - Expose session token usage via `GET /api/v1/ai/sessions/{session_id}` for frontend awareness.
- Acceptance criteria:
  - When context is refreshed, the AI successfully re-fetches current course state via tool calls.
  - The user sees an informational message that context was refreshed, not an error.
  - Active proposals from before the refresh remain usable.
  - Session token usage tracking prevents silent context loss.

### US-AI-040 - Support AI Content Versioning and Rollback

As an Admin, I want AI-authored changes to be versioned with rollback capability, so that problematic AI-generated content can be reverted without manual reconstruction.

- Source flow: 28. AI Content Versioning and Rollback.
- Priority: COULD for MVP, SHOULD for production.
- Depends on: US-AI-010, US-AI-020.
- Functional details:
  - Every applied AI mutation stores a before-snapshot enabling point-in-time rollback.
  - Admins can inspect the change history for a course or page and select a rollback target.
  - Rollback creates a new proposal (not a direct mutation) so the safety gating pipeline still applies.
- Technical details:
  - Store `before_snapshot` in `ai_audit_logs` with full page/component serialization before mutation.
  - Implement `POST /api/v1/ai/rollback` that accepts an audit log entry ID and creates a rollback proposal with the before-snapshot as the target state.
  - Rollback proposals follow the standard propose → validate → confirm → apply pipeline.
  - Track rollback events in audit with link to the original mutation and the rollback proposal.
- Acceptance criteria:
  - Every applied AI mutation has a before-snapshot queryable in audit.
  - Admin can initiate a rollback from any audit entry, producing a preview of the restored state.
  - Rollback apply is gated by the same safety pipeline as forward mutations.
  - Rollback audit trail links original mutation → rollback proposal → restored state.

### US-AI-041 - Implement Async Preview Generation Service

As an Author, I want page and course previews to be generated asynchronously, so that the AI chat remains responsive while previews render in the background.

- Source flow: 29. Async Preview Generation Service.
- Priority: COULD for MVP, SHOULD for production UX.
- Depends on: US-AI-009, US-AI-024.
- Functional details:
  - After a proposal is created, a preview rendering job is queued and processed by isolated workers.
  - The frontend polls for preview readiness and renders it when available.
  - Preview generation does not block the chat from accepting new user input.
- Technical details:
  - Implement `app/services/ai/preview_service.py` with a job queue for rendering page/course previews from proposal data.
  - Previews use the existing renderer pipeline to produce HTML fragments consistent with the course editor and SCORM output.
  - Store rendered preview in `ai_proposals` table as `preview_html` and `preview_status` (pending/ready/failed).
  - Frontend polls `GET /api/v1/ai/proposals/{proposal_id}/preview` until status is ready.
- Acceptance criteria:
  - A proposal preview is rendered within 5 seconds of proposal creation.
  - Failed preview generation returns a graceful error with retry option, not a broken UI.
  - Chat input remains enabled while preview is generating.
  - Preview output is visually consistent with the editor and SCORM render.

### US-AI-042 - Version System Prompts and Enable A/B Testing

As an AI Platform Engineer, I want versioned system prompts with A/B testing capability, so that prompt improvements can be measured and rolled out safely.

- Source flow: 30. System Prompt Versioning and A/B Testing.
- Priority: COULD for MVP, SHOULD for ongoing improvement.
- Depends on: US-AI-023, US-AI-031.
- Functional details:
  - System prompts are stored as versioned artifacts with metadata (version, effective date, author, change description).
  - A/B testing splits traffic between prompt versions and measures acceptance rate, edit distance, and user satisfaction per variant.
  - Prompt versions can be rolled back instantly if a new version underperforms.
- Technical details:
  - Store system prompts in `ai_prompt_versions` table with `version`, `prompt_text`, `model_target`, `status` (draft/active/deprecated), and `performance_metrics`.
  - Implement `app/services/ai/prompt_manager.py` that resolves the active prompt version for a given session based on A/B cohort assignment.
  - Cohort assignment is deterministic per session (hash-based) and logged for analysis.
  - Track per-prompt-version metrics: acceptance rate, mean edit distance, validation error rate, user rating.
- Acceptance criteria:
  - Changing the active prompt version does not require a server restart.
  - A/B test results show statistically significant differences between variants within 100 sessions.
  - Rolling back a prompt version takes effect for new sessions within one configuration refresh cycle.
  - Prompt version is recorded in proposal provenance and audit metadata.

## MVP Cut Recommendation

### Sprint 0 — Auth/AuthZ/Tenancy Prerequisites (MUST complete first)

**US-AI-PR01 through US-AI-PR05** are non-negotiable prerequisites. They provide mock authentication, authorization, multi-tenancy context, session middleware, and user/org resolution with `# TODO(AUTH/AUTHZ/TENANT/SESSION/USER):` markers where real services will plug in. No AI story can be implemented without these foundations. See [PREREQUISITE_MOCK_STORIES.md](PREREQUISITE_MOCK_STORIES.md) for full specifications.

### Core MVP

The smallest safe MVP should include US-AI-001 through US-AI-014 plus US-AI-021 through US-AI-025, US-AI-030, and US-AI-049. That delivers chat-based page refinement, create/update/delete proposal safety with confirmation tokens, prompt safety guardrails, frontend AI integration, and course assembly into the existing editor — without taking on file ingestion, RAG, or advanced operational controls first.

### File-Import MVP

Add US-AI-016, US-AI-017, US-AI-019, US-AI-029, and US-AI-034. Similar-course retrieval can ship independently as US-AI-015 because it is read-only and non-blocking.

### Production Hardening

Add US-AI-026 through US-AI-028, US-AI-032, US-AI-033, US-AI-035 through US-AI-036, US-AI-038 through US-AI-040, and US-AI-043, US-AI-048, US-AI-050.

### Ongoing Improvement (post-launch)

US-AI-031, US-AI-037, US-AI-041, US-AI-042, US-AI-044, US-AI-045, US-AI-046, US-AI-047.
