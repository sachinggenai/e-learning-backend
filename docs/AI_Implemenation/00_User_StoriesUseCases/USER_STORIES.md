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

## Current Backend Alignment

- Existing reusable backend surfaces: `/api/v1/courses`, `/api/v1/courses/{courseId}/pages`, `/api/v1/courses/validate`, `/api/v1/imports/analyze`, `/api/v1/imports/jobs/{job_id}`, `/api/v1/imports/jobs/{job_id}/commit`, `/api/v1/media/upload`.
- Existing persistence and repository surfaces: `CourseRecord`, `PageRecord`, `ComponentRecord`, `TemplateRecord`, `TemplateDefinition`, `ImportJob`, `CourseRepository`, `PageRepository`, `ComponentRepository`, `TemplateRepository`, `ImportJobRepository`.
- Planned AI additions: `/api/v1/ai/*` routers, AI session persistence, proposal persistence, confirmation tokens, RAG index, document ingestion route, audit/outbox tables, AI telemetry, model routing.
- The requested `/api/v1/files/upload` document route is not implemented today; current package ingestion is `/api/v1/imports/analyze`, and media upload is `/api/v1/media/upload`.

## Canonical Dependency Order

| Order | Story | Primary dependency | Unlocks |
|---:|---|---|---|
| 1 | US-AI-001 Preserve manual authoring | None | Safe AI rollout |
| 2 | US-AI-002 AI feature flags and model config | None | Controlled enablement |
| 3 | US-AI-003 Isolated AI API module | US-AI-002 | All AI routes |
| 4 | US-AI-004 AI persistence foundations | US-AI-003 | Sessions, proposals, audit |
| 5 | US-AI-005 Tool and template contract registry | US-AI-003 | Tool calls, validation |
| 6 | US-AI-006 AI session creation | US-AI-004, US-AI-005 | Scoped tools |
| 7 | US-AI-007 Page list and fetch tools | US-AI-006 | Proposal context |
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

## MVP Cut Recommendation

The smallest safe MVP should include US-AI-001 through US-AI-014 plus US-AI-021 and US-AI-022. That delivers chat-based page refinement and create/update/delete proposal safety without taking on file ingestion or RAG first.

The file-import MVP should then add US-AI-016, US-AI-017, and US-AI-019. Similar-course retrieval can ship independently as US-AI-015 because it is read-only and non-blocking.
