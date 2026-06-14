# US-BKND-AI-008 -- Unify Course, Page, Schema, Export, and Accessibility Validation

**Priority:** MUST
**Depends on:** US-BKND-AI-005 (Tool and template contract registry), US-BKND-AI-007 (Page list and fetch tools)
**Unlocks:** US-BKND-AI-009 (Generic proposal lifecycle), US-BKND-AI-018 (Validation report UI), US-BKND-AI-035 (Accessibility compliance), US-BKND-AI-038 (SCORM export readiness)

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 Detailed User Story

As a Reviewer (Author, Quality Assurance, or Admin), I want a single unified server-side validation pipeline that checks AI-proposed changes and existing course content against schema rules, template business rules, SCORM export requirements, and WCAG accessibility standards. The pipeline must return structured, categorized results (errors and warnings with field paths, severity, remediation hints) so that invalid content cannot be applied or exported, and users get clear guidance on what to fix.

### 1.2 Numbered Functional Requirements

1. **FR-001: Unified validation endpoint.** The system shall expose a single validation operation (`validate_course`) that accepts a session_id and an optional `validation_scope` parameter (`schema_only`, `business_rules`, `scorm_compliance`, `accessibility`, or `full`). The default scope is `full`.

2. **FR-002: Schema validation.** Validate proposed page data against the template-specific JSON Schema stored in the `TemplateDefinition` registry for that `template_type`. A `text-content` page missing the `content` field must produce a blocking error with field path `data.content`.

3. **FR-003: Page-level business rule validation.** Enforce template-specific constraints: `tabs` must have 2-6 tabs; `accordion` must have 2-20 panels; `click-reveal` must have 2-10 items; `final-assessment` must have 3-50 questions with a valid `passing_score` (0-100); each question must have at least one correct answer.

4. **FR-004: Course-level structural validation.** Validate that: the course has at least one page; page order indices form a zero-based contiguous sequence; no duplicate page IDs exist; all page `template_type` values are in the active allowlist.

5. **FR-005: SCORM export readiness validation.** Check that all component types referenced in pages are present in the `RendererManifest` as exportable types; assessment scoring is within SCORM limits (maxScore <= 100); all media asset references resolve to valid stored assets; theme and style data is serializable.

6. **FR-006: Accessibility compliance validation.** Check for: descriptive page titles (non-empty, min 3 chars); image components have non-empty `altText`; assessment instructions are present and non-empty (`introText` on `final-assessment`); tab/accordion structures have field hints compatible with ARIA labeling; heading hierarchy within content is semantically valid. Accessibility violations are always returned as warnings (not blocking errors) with specific remediation hints.

7. **FR-007: Proposal-scoped validation (differential).** When validating a proposal (not a full course), only validate the changed scope -- the proposed page(s) plus any cross-cutting dependencies (e.g., if deleting a page that is a navigation target, flag the orphaned navigation link). The unchanged remainder of the course is assumed valid from its last validation timestamp.

8. **FR-008: Categorized output.** The validation result shall contain three top-level lists: `errors` (blocking -- proposal cannot be applied), `warnings` (non-blocking -- user should review), and `info` (suggestions only). Each entry has: `code`, `page_id` (optional), `field` (JSON path string), `message`, `severity` (`error`/`warning`/`info`), and optional `hint` (suggestion for fix).

9. **FR-009: Integration with proposal gating.** Before any `apply_*` tool call executes, the system MUST run the unified validation pipeline on the proposal content. If any `error`-severity issues are found, the apply is rejected with `VALIDATION_ERROR` status and the full validation result is returned. The LLM receives the validation result and may retry with corrected data (max 2 automatic retries per proposal).

10. **FR-010: Integration with export pipeline.** The `POST /export/scorm/{courseId}` endpoint shall run the same unified validation (scope: `full`) before generating the ZIP. If blocking errors exist, the export is rejected with HTTP 422 and the structured validation detail array. Non-blocking warnings are optionally included as `X-Export-Warnings` headers.

### 1.3 Step-by-Step User Flows

#### Happy Path -- Full Course Validation

1. User (or AI agent) calls `validate_course(session_id=..., validation_scope="full")`.
2. System loads the course from DB using the session's `course_id`.
3. System iterates over all pages in order.
4. For each page, the system resolves the `template_type` from the page record and loads the corresponding JSON Schema from `TemplateDefinition`.
5. Schema validation runs against the page `data` field. Passes.
6. Business rule validation runs against the page data (tab counts, assessment question counts, etc.). Passes.
7. SCORM export validation runs: each component type is checked against the `RendererManifest`. Passes.
8. Accessibility validation runs: page title length, alt-text presence on images, assessment instructions. Passes.
9. Course-level validation checks: page count > 0, order contiguous, no duplicate IDs. Passes.
10. System returns `{"is_valid": true, "errors": [], "warnings": [], "info": []}`.

#### Alternate Path -- Validation with Warnings

1. User validates course. Schema and business rules pass.
2. Accessibility check finds an image component with empty `altText`.
3. System includes a warning: `{"code": "MISSING_ALT_TEXT", "page_id": "abc-123", "field": "components[0].data.altText", "severity": "warning", "message": "Image component is missing alt text", "hint": "Add a descriptive alt text for screen readers"}`.
4. Course-level and SCORM checks pass.
5. Result: `{"is_valid": true, "errors": [], "warnings": [{"code": "MISSING_ALT_TEXT", ...}], "info": []}`.
6. User can still apply or export; the warning is displayed in the UI.

#### Error Path -- Blocking Validation Failure

1. AI agent calls `propose_create_page` with a `final-assessment` template containing only 1 question.
2. System runs validation on the proposal data:
   - Schema validation: passes (data structure matches schema).
   - Business rule validation: **fails** -- `final-assessment` requires at least 3 questions.
3. System returns proposal with `validation_status: "error"` and a validation message: `{"code": "ASSESSMENT_MIN_QUESTIONS", "field": "data.questions", "severity": "error", "message": "Final assessment must have at least 3 questions", "hint": "Add 2 more questions to meet the minimum requirement"}`.
4. The AI agent receives the result, fixes the data (adds 2 more questions), and retries the proposal.
5. Second attempt: all validations pass. Proposal is now `validation_status: "valid"`.

#### Error Path -- Stale Course State

1. User A creates a session and fetches page list. User B simultaneously deletes page-3.
2. User A's AI agent calls `propose_update_page(page_id=page-3, patch={...})`.
3. Validation pipeline first checks that `page-3` still exists and belongs to session's `course_id`.
4. Page not found. Validation returns: `{"code": "PAGE_NOT_FOUND", "field": "page_id", "severity": "error", "message": "Page no longer exists in this course", "hint": "Call list_pages to refresh course state"}`.
5. The AI agent calls `list_pages`, discovers the page was deleted, and informs the user.

### 1.4 UI/UX Requirements (for US-BKND-AI-018 Validation Report UI)

1. The validation result must render in a panel with three colored sections: red for errors, amber for warnings, blue for info.
2. Each entry must be clickable, navigating the user to the specific page and field in the editor.
3. The proposal apply button must be disabled (greyed out) when blocking errors exist, with a tooltip: "Fix all errors before applying".
4. Warnings should be visible but not block the apply flow.
5. A "Re-validate" button allows the user to re-run validation after making manual edits.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### `POST /api/v1/ai/tools/validate_course`

**Headers:**
```
Authorization: Session {session_id}
Content-Type: application/json
```

**Request Body:**
```json
{
  "session_id": "string (UUID)",
  "validation_scope": "full"
}
```

`validation_scope` enum: `"schema_only"`, `"business_rules"`, `"scorm_compliance"`, `"accessibility"`, `"full"`

**Response Body (200 OK):**
```json
{
  "is_valid": true,
  "errors": [],
  "warnings": [
    {
      "code": "MISSING_ALT_TEXT",
      "page_id": "abc-123",
      "field": "components[0].data.altText",
      "message": "Image component is missing alt text",
      "severity": "warning",
      "hint": "Add a descriptive alt text for screen readers"
    }
  ],
  "metadata": {
    "validated_at": "2026-06-14T10:30:00Z",
    "schema_version": "1.0.0",
    "pages_checked": 5,
    "duration_ms": 47
  }
}
```

**Error Response (403 Unauthorized):**
```json
{
  "status": "error",
  "code": "PERMISSION_DENIED",
  "message": "Session invalid or expired",
  "details": {},
  "retryable": false
}
```

**Error Response (422 Unprocessable -- validation errors present):**
```json
{
  "is_valid": false,
  "errors": [
    {
      "code": "ASSESSMENT_MIN_QUESTIONS",
      "page_id": "xyz-789",
      "field": "data.questions",
      "message": "Final assessment must have at least 3 questions",
      "severity": "error",
      "hint": "Add 2 more questions"
    },
    {
      "code": "PAGE_ORDER_GAP",
      "page_id": null,
      "field": "pages",
      "message": "Page orders must be contiguous from 0 (missing index 2)",
      "severity": "error",
      "hint": "Reindex page orders via PATCH /courses/{courseId}/pages/reorder"
    }
  ],
  "warnings": [],
  "metadata": {
    "validated_at": "2026-06-14T10:31:00Z",
    "schema_version": "1.0.0",
    "pages_checked": 5,
    "duration_ms": 120
  }
}
```

**Error Response (500 Internal Server Error):**
```json
{
  "status": "error",
  "code": "SERVER_ERROR",
  "message": "Internal validation error",
  "details": {"errorId": "a1b2c3d4e5f6"},
  "retryable": true
}
```

**All HTTP status codes:**
| Code | Description |
|------|-------------|
| 200 | Validation completed (may still have errors/warnings in body) |
| 401 | Missing or invalid Authorization header |
| 403 | Session expired, invalid, or page outside session course scope |
| 422 | Course data has blocking validation errors (redundant with body, kept for REST purity) |
| 500 | Unexpected internal error |

#### `POST /api/v1/courses/validate` (extended existing endpoint)

Existing endpoint at `app/routers/courses.py` line 465 must be extended to also accept a `validation_scope` parameter and call the unified pipeline when AI-mode is active. Backward compatibility is maintained: without the parameter, it runs the legacy validation only.

### 2.2 Database Schema DDL

No new tables are required for this story. Validation is a computation over existing data. However, the following existing tables are involved:

```sql
-- Existing: courses
CREATE TABLE courses (
    id SERIAL PRIMARY KEY,
    course_id VARCHAR(64) UNIQUE NOT NULL,
    title VARCHAR(200) NOT NULL,
    status VARCHAR(32) DEFAULT 'draft',
    json_data JSONB NOT NULL,
    description TEXT,
    theme_json JSONB,
    custom_css TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_courses_course_id ON courses(course_id);

-- Existing: templates (PageRecord)
CREATE TABLE templates (
    id SERIAL PRIMARY KEY,
    course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
    template_uid VARCHAR(100) NOT NULL,
    template_type VARCHAR(100) NOT NULL,
    schema_signature VARCHAR(64),
    title VARCHAR(200) NOT NULL,
    order_index INTEGER NOT NULL,
    json_data JSONB NOT NULL,
    style_json JSONB,
    custom_css TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_templates_course_id ON templates(course_id);
CREATE INDEX idx_templates_uid ON templates(template_uid);

-- Existing: template_definitions (schemas for validation)
CREATE TABLE template_definitions (
    id SERIAL PRIMARY KEY,
    template_type VARCHAR(100) UNIQUE NOT NULL,
    schema_json JSONB NOT NULL,
    render_template_html TEXT NOT NULL,
    schema_signature VARCHAR(64),
    allowed_renderers JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Existing: page_components (component-level data)
CREATE TABLE page_components (
    id SERIAL PRIMARY KEY,
    component_id VARCHAR(100) UNIQUE NOT NULL,
    page_id VARCHAR(100) NOT NULL REFERENCES templates(template_uid) ON DELETE CASCADE,
    course_id VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    component_type VARCHAR(100) NOT NULL,
    data JSONB NOT NULL,
    styling JSONB,
    custom_css TEXT,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_page_components_page_id ON page_components(page_id);
CREATE INDEX idx_page_components_course_id ON page_components(course_id);
```

A new index is recommended for performance:

```sql
CREATE INDEX idx_template_definitions_type ON template_definitions(template_type);
```

### 2.3 Service/Module Design

#### New Service: `app/services/validation/unified_validator.py`

```python
class UnifiedValidator:
    """
    Orchestrates the full validation pipeline.
    
    Constructor Dependencies:
    - db_session: AsyncSession (SQLAlchemy)
    - template_definition_repo: TemplateDefinitionRepository
    - page_component_repo: PageRepository (for component data)
    - component_type_repo: ComponentTypeRepository
    - session_service (for loading current course state)
    
    Methods:
    """

    async def validate_course(
        self,
        session_id: str,
        scope: ValidationScope = ValidationScope.FULL,
    ) -> ValidationResult:
        """Full course validation. Loads course from session context."""

    async def validate_proposal(
        self,
        session_id: str,
        proposal: ProposalRecord,
        scope: ValidationScope = ValidationScope.FULL,
    ) -> ValidationResult:
        """Proposal-scoped (differential) validation."""

    async def validate_export_ready(
        self,
        course_id: str,
        pages: list[PageRecord],
        components: dict[str, list[ComponentRecord]],
    ) -> ExportValidationResult:
        """Export-specific validation subset."""
```

#### Internal Validator Classes (all in `app/services/validation/`)

```python
class SchemaValidator:
    """Validates page data against TemplateDefinition schema_json."""
    async def validate_page_data(self, template_type: str, data: dict) -> list[ValidationMessage]: ...

class BusinessRuleValidator:
    """Template-specific business rules (counts, required fields, scoring ranges)."""
    async def validate_page(self, template_type: str, data: dict) -> list[ValidationMessage]: ...
    async def validate_course_structure(self, pages: list[PageRecord]) -> list[ValidationMessage]: ...

class ExportReadinessValidator:
    """SCORM export compatibility checks via RendererManifest and ExportValidator."""
    async def validate_component_types(self, components: list[ComponentRecord]) -> list[ValidationMessage]: ...
    async def validate_asset_references(self, assets: list) -> list[ValidationMessage]: ...
    async def validate_scoring_rules(self, data: dict) -> list[ValidationMessage]: ...

class AccessibilityValidator:
    """WCAG 2.1 AA checks on page/component data."""
    async def validate_page(self, page: PageRecord, components: list[ComponentRecord]) -> list[ValidationMessage]: ...
    async def validate_image_alt_text(self, component: ComponentRecord) -> list[ValidationMessage]: ...
    async def validate_assessment_instructions(self, data: dict) -> list[ValidationMessage]: ...
    async def validate_heading_hierarchy(self, content: str) -> list[ValidationMessage]: ...
```

#### Data Classes (in `app/services/validation/models.py`)

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional

class ValidationScope(str, Enum):
    SCHEMA_ONLY = "schema_only"
    BUSINESS_RULES = "business_rules"
    SCORM_COMPLIANCE = "scorm_compliance"
    ACCESSIBILITY = "accessibility"
    FULL = "full"

class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

class ValidationMessage(BaseModel):
    code: str
    page_id: Optional[str] = None
    field: str = ""
    message: str
    severity: Severity
    hint: Optional[str] = None

class ValidationMetadata(BaseModel):
    validated_at: str
    schema_version: str = "1.0.0"
    pages_checked: int = 0
    duration_ms: int = 0

class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[ValidationMessage] = []
    warnings: list[ValidationMessage] = []
    info: list[ValidationMessage] = []
    metadata: ValidationMetadata
```

### 2.4 Configuration Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `VALIDATION_SCHEMA_VERSION` | string | `"1.0.0"` | Current schema version stamped into validation metadata |
| `VALIDATION_MAX_PAGES` | int | `200` | Max pages to validate in a single call (circuit breaker) |
| `VALIDATION_TIMEOUT_SECONDS` | int | `30` | Max wall-clock time for a full validation run |
| `VALIDATION_ACCESSIBILITY_ENABLED` | bool | `true` | Feature flag toggling accessibility checks independently |
| `VALIDATION_EXPORT_ENABLED` | bool | `true` | Feature flag toggling SCORM export checks independently |
| `AI_VALIDATION_MAX_RETRIES` | int | `2` | Max automatic LLM retries per proposal after validation failure |

### 2.5 Integration Points

| Integration | Direction | Details |
|-------------|-----------|---------|
| `TemplateDefinitionRepository` | Read | Loads `schema_json` per `template_type` for schema validation |
| `PageRepository` (`page_component_repo`) | Read | Loads `PageRecord` list for a course; loads `ComponentRecord` per page |
| `ComponentTypeRepository` | Read | Resolves component type existence and allowed renderers |
| `TemplateRepository` | Read | Loads `TemplateRecord` for template-based course paths |
| `RendererManifest` (`app/services/renderer_manifest.py`) | Read | Checks if component types are exportable; gets fallback renderers |
| `ExportValidator` (`app/services/export_validator.py`) | Delegate | Reuses its component-type, asset, and style validation logic |
| `CourseRepository` | Read | Loads `CourseRecord` to get course-level settings, theme |
| `SessionService` (US-BKND-AI-006) | Read | Resolves `session_id` to `course_id` and validates permissions |
| `ProposalService` (US-BKND-AI-009) | Called-by | Proposal `apply_*` calls `UnifiedValidator.validate_proposal` before persisting |
| `App.main` | Startup | Registers `app/services/validation/` module and seeds default schema version |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| P50 latency, full validation (10 pages) | < 200 ms | Server-side timer in `ValidationMetadata.duration_ms` |
| P95 latency, full validation (10 pages) | < 500 ms | Same |
| P99 latency, full validation (50 pages) | < 2000 ms | Same |
| P50 latency, schema-only (1 page proposal) | < 50 ms | Same |
| Throughput | 100 concurrent validation calls/minute | Load test |
| Maximum pages per call (circuit breaker) | 200 | Return 422 "too many pages" beyond this |

### 3.2 Security Requirements

| Requirement | Detail |
|-------------|--------|
| AuthZ model | Every `validate_course` call validates that `session_id` maps to a non-expired session whose `user_id` matches the authenticated caller, and whose `course_id` corresponds to a course the user has access to. |
| Tenant isolation | All queries scope to `organization_id` via the session. Cross-tenant data is never loaded. |
| Input validation | `session_id` is validated as UUID format. `validation_scope` is validated against enum. DB query parameters are parameterized (SQLAlchemy ORM handles this). |
| Rate limiting | 100 validation calls per user per hour (same as general tool-call limit from system architecture). |
| Denial-of-service protection | `VALIDATION_MAX_PAGES=200` prevents a malicious large-course payload from consuming too many resources. |

### 3.3 Reliability

| Concern | Strategy |
|---------|----------|
| Error codes catalog | See below |
| Retry strategy | Validation is read-only and idempotent. Clients may retry on HTTP 500/503 with exponential backoff (1s, 2s, 4s). HTTP 422 (validation errors in content) is NOT a retry condition for the same payload -- the caller must fix data first. |
| Graceful degradation | If `VALIDATION_ACCESSIBILITY_ENABLED=false`, accessibility checks are skipped silently. If `VALIDATION_EXPORT_ENABLED=false`, SCORM checks are skipped. Schema and business rule validation are always active. |
| Idempotency | Validating the same course with the same scope always returns the same result (assuming no DB mutations in between). No side effects. |

#### Error Codes Catalog

| Code | HTTP Status | Description | Retryable |
|------|-------------|-------------|-----------|
| `PERMISSION_DENIED` | 403 | Session invalid/expired/wrong user | No |
| `SESSION_EXPIRED` | 403 | Session TTL exceeded | No (re-create session) |
| `COURSE_NOT_FOUND` | 404 | Course ID from session not in DB | No |
| `TOO_MANY_PAGES` | 422 | Exceeded `VALIDATION_MAX_PAGES` | Yes (reduce scope) |
| `VALIDATION_TIMEOUT` | 500 | Exceeded `VALIDATION_TIMEOUT_SECONDS` | Yes |
| `SERVER_ERROR` | 500 | Unexpected internal error | Yes |
| `SCHEMA_VALIDATION_ERROR` | 200 in body | Template data fails JSON Schema | Yes (fix data) |
| `MISSING_REQUIRED_FIELD` | 200 in body | Required field absent from data | Yes (fix data) |
| `ASSESSMENT_MIN_QUESTIONS` | 200 in body | Assessment has < 3 questions | Yes (fix data) |
| `TABS_MIN_ITEMS` | 200 in body | Tabs template has < 2 tabs | Yes (fix data) |
| `ACCORDION_MIN_ITEMS` | 200 in body | Accordion has < 2 panels | Yes (fix data) |
| `CLICK_REVEAL_MIN_ITEMS` | 200 in body | Click-reveal has < 2 items | Yes (fix data) |
| `PAGE_ORDER_GAP` | 200 in body | Page orders not contiguous | Yes (re-order pages) |
| `PAGE_NO_COMPONENTS` | 200 in body | Page has zero components | Yes (add component) |
| `UNSUPPORTED_COMPONENT_TYPE` | 200 in body | Component type not in renderer manifest | Yes (change type) |
| `UNSUPPORTED_TEMPLATE_TYPE` | 200 in body | Template type not in allowlist | No (reject proposal) |
| `MISSING_ALT_TEXT` | 200 in body | Image component missing alt text | Yes (add alt text) |
| `ASSESSMENT_MISSING_INSTRUCTIONS` | 200 in body | Assessment has no introText | Yes (add instructions) |
| `EXPORT_SCORING_LIMIT` | 200 in body | maxScore > 100 (SCORM limit) | Yes (fix score) |
| `COURSE_EMPTY` | 200 in body | Course has zero pages | Yes (add pages) |
| `DUPLICATE_PAGE_ID` | 200 in body | Two pages share the same ID | Yes (change one ID) |

### 3.4 Scalability

| Aspect | Design |
|--------|--------|
| Statelessness | `UnifiedValidator` is stateless between calls. All state is loaded from DB per invocation. |
| Horizontal scaling | Multiple instances can run validation concurrently. No shared in-memory state. |
| Connection pooling | SQLAlchemy `AsyncSession` uses a connection pool (default `pool_size=10`, `max_overflow=20`). Validation reads are short-lived; pool should be sufficient. |
| Read replicas | Validation is read-only. It can be routed to a read replica by setting `VALIDATION_DATABASE_URL` to a read-only connection string. |

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists in the Codebase Today (Reusable)

| File | What Exists | How to Reuse |
|------|-------------|--------------|
| `app/routers/courses.py` (lines 465-751) | `POST /api/v1/courses/validate` endpoint with `CourseValidationRequest`, `ValidationResult`, `ValidationError` models | Extend to call `UnifiedValidator` when AI session context is present. Keep legacy path unchanged for backward compat. |
| `app/services/export_validator.py` | `ExportValidator` class with `validate()` method checking `RendererManifest` support, required fields, MCQ structures, style config, asset refs, interaction config | `ExportReadinessValidator` delegates to `ExportValidator.validate()` as its first check, then adds SCORM-specific rules. |
| `app/services/renderer_manifest.py` | `get_renderer_manifest()` function returning `RendererManifest` with `is_supported()`, `get_fallback()`, `get_supported_types()` | Used by `ExportReadinessValidator` to check component type exportability. |
| `app/utils/validation.py` | `CourseValidator` class with `validate_course()`, `_validate_business_rules()`, `_validate_template()`, `_validate_mcq_template()` | `BusinessRuleValidator` reuses the MCQ/question validation logic. `SchemaValidator` replaces the JSON Schema path (currently skipped in code at line 79-86). |
| `app/models/course.py` | `TemplateData`, `Template`, `Course` Pydantic models with `@field_validator` / `@validator` decorators enforcing structural rules (template ordering, MCQ question shapes, assessment rules) | These are already used by `validate_course_json` dependency. The new pipeline should call `Course(**course_data)` as a fast structural validation step, then do deeper template-specific checks separately. |
| `app/models/export_contract.py` | `ExportValidationResult`, `ExportValidationError` Pydantic models | Map to the new `ValidationMessage` format in the validation pipeline. |
| `app/models/persisted_course.py` | `CourseRecord`, `TemplateRecord`, `TemplateDefinition` SQLAlchemy ORM models | `SchemaValidator` reads `TemplateDefinition.schema_json` for template schemas. `BusinessRuleValidator` reads `TemplateRecord.json_data` for page data. |
| `app/repositories/template_definition_repo.py` | `TemplateDefinitionRepository.get_by_type_key()` | Used by `SchemaValidator` to load per-template JSON Schema. |
| `app/repositories/page_component_repo.py` | `PageRepository.list_by_course()`, `ComponentRepository.list_by_page()` | Used by validation pipeline to load pages and components for a course. |
| `app/repositories/course_repo.py` | `CourseRepository.get_by_course_id()` | Used at pipeline entry to load the `CourseRecord`. |
| `app/utils/error_envelope.py` | `build_error()`, `api_http_exception()` | Reuse for 403/404/500 error responses. |
| `app/utils/feature_flags.py` | `FeatureFlagService`, `is_feature_enabled()` | Wrap validation scope toggles (accessibility, export) behind feature flags. |

### 4.2 What Must Be Built Net-New

| Component | Reason |
|-----------|--------|
| `app/services/validation/` package | No unified validation service exists. Today validation is scattered across `CourseValidator` (utils), `ExportValidator` (services), and in-line checks in routers. |
| `app/services/validation/unified_validator.py` | `UnifiedValidator` orchestrator class with `validate_course()` and `validate_proposal()` methods. |
| `app/services/validation/models.py` | `ValidationResult`, `ValidationMessage`, `ValidationScope`, `Severity` data classes. |
| `app/services/validation/schema_validator.py` | `SchemaValidator` -- currently the JSON Schema path in `CourseValidator._validate_against_schema()` is skipped (line 79-86 in `utils/validation.py`). Must now be implemented fully. |
| `app/services/validation/business_rule_validator.py` | `BusinessRuleValidator` -- consolidates business rules currently duplicated across `CourseValidator`, `export_validator.py`, and `course.py` model validators. |
| `app/services/validation/export_readiness_validator.py` | `ExportReadinessValidator` -- wraps `ExportValidator` and adds SCORM-specific checks (scoring limits, renderer manifest completeness). |
| `app/services/validation/accessibility_validator.py` | `AccessibilityValidator` -- entirely new. No accessibility checks exist in the codebase today. |
| AI tool adapter for `validate_course` | Adapter function in `app/routers/ai_tools.py` (from US-BKND-AI-003) that wraps `UnifiedValidator.validate_course()` into the tool-calling contract shape. |

### 4.3 What Existing Code Must Be Modified (with Non-Regression Constraints)

| File | Modification | Non-Regression Constraint |
|------|-------------|--------------------------|
| `app/routers/courses.py` (line 465, `validate_course` endpoint) | Add optional `validation_scope` query parameter. If present and AI feature flag is enabled, delegate to `UnifiedValidator` instead of the legacy inline logic. | When `validation_scope` is absent (or feature flag disabled), the endpoint must behave identically to today -- same `ValidationResult` shape, same validation rules. |
| `app/routers/export.py` (line 719, `export_persisted_course`) | Before zipping, call `UnifiedValidator.validate_export_ready()` with the resolved pages and components. If `is_valid` is false, raise 422 with structured errors. | Legacy export path must remain untouched when AI modules are not registered. The existing `_validate_course_for_export()` helper (line 336) should be kept as fallback. |
| `app/utils/validation.py` | The `CourseValidator` class should be refactored to delegate to `BusinessRuleValidator` for template-specific rules once the new package is stable. Until then, both coexist. | Existing `validate_course_json` FastAPI dependency must continue to work unchanged for the legacy `POST /export` endpoint (which receives raw JSON, not a course ID). |
| `app/main.py` | Import and register the `app/services/validation/` module at startup (similar to how `_verify_critical_contracts` works today). | Registration must be idempotent and fail gracefully with a warning log if the validation module is missing. |
| `app/services/export_validator.py` | The `ExportValidator` class should expose a new method `validate_readiness(course_data) -> ExportValidationResult` that matches the new pipeline's interface, so `ExportReadinessValidator` can call it without adapting output format. | Existing `validate()` method must remain unchanged; existing callers (if any) must not break. |

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansion Points (Future Sprints)

1. **Asynchronous validation with progress streaming.** For courses with 100+ pages, run validation as a background job (via the durable workflow engine from US-BKND-AI-034). The tool call returns a `job_id` immediately, and the frontend polls `GET /api/v1/ai/validation/{job_id}` for progress and partial results.

2. **Validation rule engine with pluggable policies.** Replace hard-coded `if template_type == "tabs":` checks with a rule registry where rules are stored in DB (`validation_rules` table) and can be added/removed at runtime without code deployment. Rules would be expressed as JSON: `{"template_type": "final-assessment", "rule": "min_questions", "params": {"min": 3}, "severity": "error"}`.

3. **Cached validation results with invalidation tokens.** Cache `ValidationResult` keyed by `(course_id, validation_scope, course_updated_at)` for TTL of 60 seconds. When a course is modified, the cache entry is invalidated. For proposal validation (where latency is more critical), always go to DB -- no caching.

### 5.2 Functional Expansion Points

1. **Custom validators per tenant/organization.** Enable organizations to define their own validation rules (e.g., "all courses in the medical org must have a sources/references page"). These would be stored as additional entries in the rule registry from 5.1.2 above.

2. **Deep learning-based accessibility scoring.** Replace the current heuristic accessibility checks (alt-text presence, heading presence) with a lightweight ML model that scores content readability, contrast compliance, and screen-reader friendliness. Scores would be returned as `info`-level messages.

3. **Cross-course consistency validation.** Validate that terminology, tone, and template usage are consistent across multiple courses in a curriculum. This would require a RAG-based similarity check (US-BKND-AI-015) as part of the validation output: "Warning: This course uses 'customer' but 3 other courses in this curriculum use 'client'."

---

## 6. VALIDATION & TESTING

### 6.1 Unit Test Scenarios (at least 5)

**Test 1: Schema validation catches missing required field**
- Input: `page_data = {"title": "Intro", "data": {}}` for `template_type = "text-content"`
- Expected: One error with `code="MISSING_REQUIRED_FIELD"`, `field="data.content"`, `severity="error"`, `is_valid=False`

**Test 2: Business rule enforces final-assessment minimum questions**
- Input: `page_data = {"title": "Quiz", "passing_score": 80, "questions": [{"question_text": "Q1", "question_type": "multiple_choice", "options": ["A", "B"], "correct_answer": "A"}]}` for `template_type = "final-assessment"`
- Expected: One error with `code="ASSESSMENT_MIN_QUESTIONS"`, `field="data.questions"`, `severity="error"`, `is_valid=False`

**Test 3: Accessibility warning for missing alt text**
- Input: `component = {"component_type": "image", "data": {"src": "https://example.com/img.png"}}` (no `altText` field)
- Expected: One warning with `code="MISSING_ALT_TEXT"`, `field="data.altText"`, `severity="warning"`, `is_valid=True`

**Test 4: Course-level structural validation catches page order gaps**
- Input: `pages = [{"order_index": 0}, {"order_index": 2}]` (missing index 1)
- Expected: One error with `code="PAGE_ORDER_GAP"`, `field="pages"`, `severity="error"`, `is_valid=False`

**Test 5: Export validation blocks unsupported component type**
- Input: `component = {"component_type": "custom-vr-viewer", "data": {}}` where `RendererManifest.is_supported("custom-vr-viewer")` returns `False` with no fallback
- Expected: One error with `code="UNSUPPORTED_COMPONENT_TYPE"`, `field="componentType"`, `severity="error"`, `is_valid=False`

**Test 6: Full validation passes for a well-formed course**
- Input: A course with 3 pages (text-content, tabs with 3 tabs, final-assessment with 5 questions), all components have alt text, page orders are [0,1,2]
- Expected: `is_valid=True`, `errors=[]`, `warnings=[]`

**Test 7: Multiple errors returned for multiple violations**
- Input: A course with a text-content page missing `content` AND a final-assessment with 1 question AND page order gap
- Expected: 3 errors in the `errors` list, each with correct `code` and `field`

### 6.2 Integration Test Scenarios (at least 3)

**Test 1: Proposal gating integration**
- Create a session via `POST /api/v1/ai/sessions`.
- Call `propose_create_page` with invalid `final-assessment` data (1 question).
- Verify response contains `validation_status: "error"` with the `ASSESSMENT_MIN_QUESTIONS` error.
- Verify NO page was created in the DB (query `templates` table).
- Call `propose_create_page` with corrected data (3 questions).
- Verify response contains `validation_status: "valid"`.

**Test 2: Export pipeline integration**
- Create a course with 1 valid page via `POST /api/v1/courses`.
- Call `POST /api/v1/courses/validate` with scope `full` -- returns `is_valid=True`.
- Call `POST /export/scorm/{courseId}` -- returns 200 with ZIP stream.
- Now add a component with an unsupported type via DB directly.
- Call `POST /export/scorm/{courseId}` again -- returns 422 with `UNSUPPORTED_COMPONENT_TYPE` in the error detail array.

**Test 3: Legacy backward compatibility**
- Call `POST /api/v1/courses/validate` (the existing endpoint) with the same payload that works today, without `validation_scope` parameter.
- Verify the response shape matches the existing `ValidationResult` model from `app/routers/courses.py` exactly (same field names, same nesting).
- Verify that enabling the AI feature flag and passing `validation_scope=full` returns additional validation dimensions (accessibility warnings, export checks) while keeping the same base validation logic.

### 6.3 E2E/Acceptance Test Scenarios (at least 2)

**E2E Test 1: AI proposes invalid page, gets blocked, fixes, applies**
1. User creates a session for a course.
2. AI calls `propose_create_page` with a `final-assessment` containing 1 question and a missing `passing_score`.
3. Validation returns error: `ASSESSMENT_MIN_QUESTIONS` and `MISSING_REQUIRED_FIELD` for `passing_score`.
4. AI corrects: adds 4 more questions (total 5) and sets `passing_score: 80`.
5. AI retries proposal. Validation returns `validation_status: "valid"`.
6. User approves in UI.
7. `apply_page_proposal` succeeds -- page created with 5 questions and passing_score=80.

**E2E Test 2: Manual course export with blocking errors rejected**
1. Admin creates a 2-page course manually via the editor.
2. Admin deletes all components from page 2 via DB (or by manipulating state).
3. Admin clicks "Export SCORM".
4. Backend runs unified validation. Finds page 2 has zero components (`PAGE_NO_COMPONENTS`).
5. Export returns HTTP 422 with structured detail: `[{"code": "PAGE_NO_COMPONENTS", "field": "pages[1].components", "message": "Page 'Summary' must contain at least one component"}]`.
6. Admin sees the error in UI, re-opens page 2, adds a component, re-exports successfully.

### 6.4 Step-by-Step Manual QA Verification Procedure

**Setup:**
1. Start the backend with `AI_AUTHORING_ENABLED=true` and all validation feature flags enabled.
2. Ensure at least 2 `TemplateDefinition` records exist (one for `text-content`, one for `final-assessment`).
3. Seed a test course with 2 pages (one `text-content` with valid data, one `final-assessment` with 1 question only -- the invalid one).

**Verification Steps:**

**Step 1: Basic validation via existing endpoint (backward compat)**
- Send `POST /api/v1/courses/validate` with `{"courseData": {"courseId": "test", "title": "T", "pages": [{"id": "p1", "title": "P1"}]}}`.
- Verify: Response is 200 JSON with `valid: false` and at least one error about missing content/fields.

**Step 2: Unified validation via AI tool adapter**
- Get a valid `session_id` from `POST /api/v1/ai/sessions`.
- Call `POST /api/v1/ai/tools/validate_course` with `{"session_id": "...", "validation_scope": "full"}`.
- Verify: Response contains `is_valid: false`. The `errors` list includes `ASSESSMENT_MIN_QUESTIONS` for the assessment page (1 question < 3).
- Verify: The `warnings` list may contain `MISSING_ALT_TEXT` if any image components lack alt text.
- Verify: `metadata.pages_checked` equals 2. `metadata.duration_ms` is a positive integer.

**Step 3: Scope filtering**
- Repeat Step 2 with `validation_scope: "schema_only"`.
- Verify: Only schema errors present; no business rule errors (ASSESSMENT_MIN_QUESTIONS should NOT appear).
- Repeat with `validation_scope: "accessibility"`.
- Verify: Only accessibility warnings present; no schema or business rule errors.

**Step 4: Proposal-scoped validation**
- Call `propose_create_page` with a valid `text-content` page. Verify `validation_status: "valid"`.
- Call `propose_create_page` with a `tabs` page containing only 1 tab. Verify `validation_status: "error"` and `code: "TABS_MIN_ITEMS"`.
- Call `apply_page_proposal` on the errored proposal without fixing. Verify: Apply fails (status `error` or `rejected`).

**Step 5: Export blocking**
- Run `POST /export/scorm/{courseId}` for the seeded course with the invalid assessment.
- Verify: HTTP 422 response with detail containing `ASSESSMENT_MIN_QUESTIONS`.
- Fix the course: Update the assessment page data to have 3+ questions.
- Run export again. Verify: HTTP 200 with ZIP stream.

**Step 6: Performance check**
- Create a course with 50 pages of varied templates.
- Measure the time for a `full` validation from the server log (`metadata.duration_ms`).
- Verify it is under 2000ms.

---

## 7. DEFINITION OF DONE

Checklist items (all must be complete for this story to be considered "Done"):

1. [ ] `app/services/validation/unified_validator.py` is implemented with `UnifiedValidator.validate_course()` and `validate_proposal()` methods.
2. [ ] `app/services/validation/schema_validator.py` is implemented and loads `TemplateDefinition.schema_json` to validate page data.
3. [ ] `app/services/validation/business_rule_validator.py` enforces all 5 MVP template business rules (tabs 2-6, accordion 2-20, click-reveal 2-10, assessment 3-50 questions, passing_score 0-100).
4. [ ] `app/services/validation/export_readiness_validator.py` delegates to `ExportValidator` and adds SCORM-specific checks (scoring limits, manifest completeness).
5. [ ] `app/services/validation/accessibility_validator.py` checks alt-text presence, assessment instructions, page title length, and heading hierarchy hints.
6. [ ] `app/services/validation/models.py` defines `ValidationResult`, `ValidationMessage`, `ValidationScope`, `Severity` data models.
7. [ ] AI tool adapter `validate_course` is registered in the tool registry and callable from the LLM via `POST /api/v1/ai/tools/validate_course`.
8. [ ] `POST /api/v1/courses/validate` existing endpoint is extended with optional `validation_scope` parameter without breaking backward compatibility.
9. [ ] `POST /export/scorm/{courseId}` runs unified validation before export and returns 422 with structured errors on blocking failures.
10. [ ] All 7 unit test scenarios pass in CI (Section 6.1).
11. [ ] All 3 integration test scenarios pass in CI (Section 6.2).
12. [ ] Both E2E test scenarios pass in CI (Section 6.3).
13. [ ] Manual QA verification procedure (Section 6.4) is executed and signed off by QA.
14. [ ] No regression in existing `POST /api/v1/courses/validate` behavior when AI feature flag is disabled.
15. [ ] No regression in existing `POST /export` and `POST /export/scorm/{courseId}` endpoints when AI feature flag is disabled.
16. [ ] Configuration variables (`VALIDATION_ACCESSIBILITY_ENABLED`, `VALIDATION_EXPORT_ENABLED`, etc.) are documented in `.env.example` and default to safe values.
17. [ ] Feature flag `validation_accessibility` and `validation_export` toggle the respective checks without affecting schema/business-rule validation.
18. [ ] Performance target verified: P50 latency < 200ms for a 10-page course, P99 < 2000ms for a 50-page course.
19. [ ] All validation error codes from the catalog (Section 3.3) are documented in the API reference (OpenAPI spec or a README).
20. [ ] Code review completed with approval from at least one other engineer.

---

## 8. TASKS & SUB-TASKS

| ID | Description | Owner Role | Est. Hours | Dependencies |
|----|-------------|------------|------------|--------------|
| T1 | **Create `app/services/validation/` package with data models** -- Implement `models.py` (`ValidationResult`, `ValidationMessage`, `ValidationScope`, `Severity`), `__init__.py` that exports all classes, and unit tests for model construction and serialization. | Backend Engineer | 4 | US-BKND-AI-005 (for `TemplateDefinition.schema_json` availability) |
| T2 | **Implement `SchemaValidator` and `BusinessRuleValidator`** -- `SchemaValidator` reads `TemplateDefinition.schema_json` and validates page data against it using `jsonschema`. `BusinessRuleValidator` encodes template-specific count/range rules for all 5 MVP templates. Unit tests for each validator in isolation. | Backend Engineer | 8 | T1 |
| T3 | **Implement `ExportReadinessValidator` and `AccessibilityValidator`** -- `ExportReadinessValidator` wraps `ExportValidator.validate()` and adds SCORM-specific checks. `AccessibilityValidator` implements WCAG 2.1 AA heuristic checks (alt-text, headings, assessment instructions). Unit tests for each. | Backend Engineer | 8 | T1, US-BKND-AI-007 (for page/component repository loading) |
| T4 | **Implement `UnifiedValidator` orchestrator and AI tool adapter** -- Orchestrator with `validate_course()` and `validate_proposal()` methods that runs the correct sub-validators based on scope. Tool adapter registered in `app/routers/ai_tools.py`. Integration tests for the full pipeline. | Senior Backend Engineer | 6 | T2, T3 |
| T5 | **Extend existing endpoints** -- Extend `POST /api/v1/courses/validate` with optional `validation_scope` (backward compat). Add validation call to `POST /export/scorm/{courseId}` before ZIP generation. Integration tests for backward compat and export blocking. | Backend Engineer | 6 | T4 |
| T6 | **Configuration, feature flags, and documentation** -- Add env vars to `.env.example`, wire feature flags in `app/utils/feature_flags.py`, document all error codes in API reference, write architecture decision record (ADR) for the unified validation design. | Backend Engineer / Tech Writer | 4 | T4 |
| T7 | **Performance testing and hardening** -- Create load test script (locust or Python) for 100 concurrent validation calls. Verify P50/P95/P99 targets. Add circuit breaker for >200 pages. Fix any bottlenecks found. | QA Engineer / Backend Engineer | 6 | T5 |

**Total estimated effort:** 42 hours (approximately 5.25 engineering days for a single developer, or 2-3 days with parallelization of T2/T3).

---