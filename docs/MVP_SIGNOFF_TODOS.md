# MVP Signoff Todos

Technical Product Owner review artifact for the backend domains: Courses, Templates, Import, Export, Media, Scoring, Analytics.

This document converts the implementation review into actionable todos with:
- Intended functional behavior
- Current implementation gap
- Technical work required
- Acceptance criteria
- Severity for MVP signoff

## Gap Matrix

| Domain | Use Case | Intended Functional Behavior | Current Status | Gap Summary | Severity |
|---|---|---|---|---|---|
| Courses | Create, read, update, delete courses | Users can manage persisted courses by public `courseId` with stable validation and consistent payloads | Mostly implemented | CRUD works, but validation model is split between legacy `templates` and newer `pages/components` flows | Medium |
| Courses | Validate course before save/export | Users can validate the same course model they later save or export, with real timestamps and consistent error categories | Partially implemented | Validation endpoint uses a separate pages-based request shape and hardcoded timestamps | Medium |
| Templates | Manage course templates | Users can create, update, reorder, delete templates for a course using the same course identifier model as other endpoints | Implemented | Template endpoints now resolve public `courseId` to internal PK, matching other course-scoped routes | Low |
| Templates | Browse component/template registry | Users can list and inspect component definitions, categories, and searchable metadata | Implemented and validated | List/categories/search/detail (including conditional ETag behavior) are now covered by tests | Low |
| Templates | Manage pages and components | Users can create pages, add components, reorder them, and update page layout/theme/completion settings | Implemented and validated | CRUD and reorder lifecycle is covered by API tests | Low |
| Import | Analyze uploaded SCORM package | Users can upload a SCORM/legacy package, infer content, extract assets, and stage previewable results | Implemented | Analyze and preview flows exist and strategy-level tests exist | Low |
| Import | Commit analyzed import to persisted course | Users can finalize an analyzed job and get a real persisted course/page/template structure | Implemented for course+template persistence | Commit now creates persisted course + normalized templates and links import job to created course | Medium |
| Export | Export raw course payload | Users can export validated course payloads to a SCORM package with correct structure | Implemented | Asset packaging now copies real files and fails explicitly when assets are missing/invalid | Low |
| Export | Export persisted course by public ID | Users can export an already-saved course by `courseId` without needing internal DB IDs | Implemented | Persisted export now resolves by `courseId` and is covered by focused tests | Low |
| Export | Export authoritative content | Users receive SCORM output derived only from real stored content and valid defaults | Partially implemented | Export adapter injects fallback YouTube URLs and placeholder quiz questions | High |
| Media | Upload, serve, list, delete media | Users can securely manage media assets used by courses and exports | Implemented | Upload/list/serve/delete exist with validation and tests | Low |
| Scoring | Configure course scoring | Users can define passing score, weights, attempts, and reporting settings | Implemented structurally | Config endpoints exist and persistence exists | Medium |
| Scoring | Calculate learner score | Users receive real scores based on stored component/question answers and scoring rules | Implemented for MCQ with persisted content lookup | Score calculation now validates component/question definitions and computes real per-question/component totals | Medium |
| Completion | Track course and page completion | Users and LMS can see real completion states derived from interactions and component criteria | Implemented for interaction and score criteria with persisted event evidence | Reads now derive completion from stored interaction events; page completion writes are persisted as events | Medium |
| Analytics | View course summary | Product and operations can see meaningful event, structure, and scoring summaries | Implemented at coarse level | Summary exists but is mostly aggregate counts rather than learner-centric analytics | Medium |
| Analytics | View learner/manager insights | Managers can inspect learner-level progress, mastery, and performance | Implemented for event-based learner aggregates | Interaction writes now persist learner identity and manager view includes learner summaries | Medium |

## Severity-Ranked Backlog

### Critical

#### TODO-001: Implement real import commit persistence
- Status: Completed (course + template persistence)
- Verification:
  - `POST /api/v1/imports/jobs/{job_id}/commit` now creates persisted course + template records.
  - Job is linked to created `courseId`.
  - Covered by `tests/test_import_discovery.py`.
- Follow-up:
  - Extend commit to page/component persistence when import payload includes component-native structures.

#### TODO-002: Fix persisted export lookup by public course ID
- Status: Completed
- Verification:
  - Persisted export now uses `get_by_course_id`.
  - Covered by `tests/test_export.py` for success and not-found paths.

#### TODO-003: Replace placeholder scoring logic with real answer evaluation
- Status: Completed for MCQ
- Verification:
  - Scoring now loads persisted component/question definitions and computes actual results.
  - Covered by `tests/test_scoring_completion_api.py`.
- Follow-up:
  - Extend evaluator for non-MCQ scored component types.

#### TODO-004: Implement real completion state evaluation
- Status: Completed for persisted event-backed completion
- Verification:
  - Completion reads derive state from persisted interaction events.
  - Page completion submissions are persisted and reflected by read endpoints.
  - Covered by `tests/test_scoring_completion_api.py`.
- Follow-up:
  - Add learner-scoped completion aggregation once learner identity is captured on writes.

### High

#### TODO-005: Remove fake export fallbacks and placeholder content generation
- Status: Completed
- Verification:
  - Persisted export no longer fabricates fallback media/questions.
  - SCORM asset packaging now copies real files and fails explicitly on missing/invalid assets.
  - Covered by `tests/test_export.py` and `tests/test_scorm_export_assets.py`.

#### TODO-006: Standardize course identifier strategy across templates and page APIs
- Status: Completed
- Verification:
  - Template CRUD now uses `/courses/{courseId}/templates`.
  - Tests updated and passing in `tests/test_templates_api.py`, `tests/test_templates_negative.py`, and downstream callers.

#### TODO-007: Add end-to-end tests for page/component CRUD
- Status: Completed
- Verification:
  - Page/component lifecycle tests added in `tests/test_page_components_api.py`.

#### TODO-008: Implement learner-scoped analytics data capture
- Status: Completed (event aggregate scope)
- Verification:
  - Interaction writes now accept/persist `learnerId`.
  - Analytics summary and manager view support learner filtering and learner aggregates.
  - Covered by `tests/test_analytics_learners.py`.

#### TODO-008A: Add automated tests for persisted export, scoring, and completion
- Status: Completed for critical coverage set
- Verification:
  - Persisted export tests added in `tests/test_export.py`.
  - Scoring/completion tests added in `tests/test_scoring_completion_api.py`.
  - Import commit tests added in `tests/test_import_discovery.py`.

### Medium

#### TODO-009: Unify course validation flows
- Status: Completed (compatibility scope)
- Verification:
  - Validation endpoint now emits real request-time timestamps.
  - Template-based payloads are checked against export `Course` model for compatibility errors.
  - Covered by `tests/test_course_validate_api.py`.

#### TODO-010: Strengthen analytics semantics beyond aggregate counts
- Status: Completed (MVP KPI scope)
- Verification:
  - Summary now includes learner/event KPIs: distinct learners, completion event rate, and average score.
  - Manager view provides learner-level aggregates and filtering.
  - Covered by `tests/test_analytics_learners.py`.

#### TODO-011: Add tests for component registry behavior
- Status: Completed
- Verification:
  - Registry API coverage added in `tests/test_component_registry_api.py`.

#### TODO-012: Add full import endpoint tests
- Status: Completed
- Verification:
  - Import API lifecycle coverage exists in `tests/test_import_discovery.py` for analyze, preview, status, and commit.

## MVP Release-Readiness Checklist

### Must Pass Before MVP Signoff

- [x] Import commit creates real persisted courses and related records.
- [x] Persisted export works with public `courseId` and exports the saved course.
- [x] Persisted export path is covered by automated tests.
- [x] Export package contains real assets or fails explicitly when assets are missing.
- [x] Scoring returns real evaluated results for supported scored component types.
- [x] Scoring calculation is covered by automated tests.
- [x] Completion endpoints reflect actual learner/interactions state.
- [x] Completion read/write flows are covered by automated tests.
- [x] All course-scoped APIs use a consistent course identifier contract.
- [x] Page/component CRUD is covered by automated tests.
- [x] Interaction writes capture learner identity when analytics is learner-scoped.
- [x] Import endpoint lifecycle is covered by automated tests.
- [x] Component registry behavior is covered by automated tests.

### Nice to Have After MVP

- [ ] Richer analytics KPIs beyond counts.
- [ ] Async export job tracking beyond current synchronous placeholder status.
- [ ] Unified validation adapter for legacy templates and page/component authoring.

## Recommended Implementation Order

1. Fix persisted export lookup and remove fake export fallbacks.
2. Implement import commit persistence.
3. Implement real scoring evaluation.
4. Implement real completion aggregation.
5. Standardize course identifier contracts.
6. Add missing tests for pages/components, component registry, and import endpoints.
7. Improve learner-aware analytics.
