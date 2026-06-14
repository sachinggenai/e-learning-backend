## US-BKND-AI-035: AI Content Accessibility Compliance

**As a** Compliance Officer,  
**I want** AI-generated course content to be validated against WCAG 2.1 AA accessibility standards before apply,  
**so that** AI does not introduce accessibility regressions and the platform remains compliant for regulated tenants.

---

### Section 1: Business Value & Priority

- **Priority:** SHOULD for MVP, MUST for regulated tenants (healthcare, finance, government).
- **Dependencies:** US-BKND-AI-008 (Unified Validation Pipeline)
- **Unlocks:** US-BKND-AI-038 (SCORM Export Readiness), SOC 2 / Section 508 attestation, enterprise sales to regulated verticals.
- **Risk if omitted:** AI-generated courses fail WCAG audits, exposing the organization to lawsuits (ADA Title III, Section 508), blocking enterprise deals, and creating manual remediation overhead estimated at 4-8 hours per course.

---

### Section 2: Functional Specification

#### 2.1 Accessibility Validation Pipeline

A new service `AccessibilityValidator` inspects every AI-proposed page/component before proposal creation. It checks:

1. **Images** -- Every component of type `content-image`, `infographic`, `hotspot`, `image-hotspots`, `carousel`, `content-media` must have `accessibilityConfig.altText` populated and non-empty.
2. **Heading hierarchy** -- Content components (`content-text`, `welcome`, `rich-text-editor`) must have a logical heading sequence (h1 -> h2 -> h3, no skips). The first heading on a page must be h1 or h2.
3. **Color contrast hints** -- Style configs with color overrides must include a `contrastNote` field indicating the contrast ratio (e.g., `"4.5:1"`) or reference a WCAG-compliant theme token.
4. **Assessment accessibility** -- MCQ, multiple-select, true-false, and fill-in-blank question text must be non-empty (screen-reader compatible). Assessment instructions (`data.content` or `data.introText`) must be present.
5. **Tab/Accordion ARIA hints** -- Tab panels must have `accessibilityConfig.role="tabpanel"` and `accessibilityConfig.ariaLabel` on each tab button. Accordion panels must have `accessibilityConfig.role="region"` and `ariaLabel` on each panel heading.
6. **Video/audio transcripts** -- `content-video`, `video-slide`, and `audio-player` components must reference a `transcript` field or have an accompanying `transcript-caption` component on the same page.
7. **Link purpose** -- `external-link` components must have descriptive link text (not "click here" pattern) and `ariaLabel` when the link text alone is insufficient.
8. **Keyboard operability** -- Interactive components (tabs, accordion, carousel) must have `accessibilityConfig.keyboardShortcuts` or a `focusOrder` specified.
9. **Language attributes** -- The course `language` field must be set and match a valid language code (from `LanguageType`). Generated HTML content should include a `lang` attribute.
10. **Form labels** -- `form` component fields must have either a visible `<label>` or `ariaLabel`.

#### 2.2 Scoring & Reporting

```
AccessibilityScore {
    score: float        // 0.0 to 1.0, per-page aggregate
    totalChecks: int
    passedChecks: int
    warnings: int       // non-blocking issues
    errors: int         // blocking issues  
}
```

- Per-page score = `(passedChecks * 1.0 + warnings * 0.5) / totalChecks` (warnings are half-credit).
- A page with any **errors** gets score 0.0 and is flagged `FAIL`.
- A page with only **warnings** gets score >= 0.5 and is flagged `WARN`.
- A page with **no issues** gets score 1.0 and is flagged `PASS`.
- Overall course score = mean of per-page scores.

#### 2.3 Integration Points

1. **Proposal validation** (US-BKND-AI-008 contract): `AccessibilityValidator.run()` is called during proposal validation. Errors are returned as `level="error"` ValidationErrors with `category="accessibility"`. Warnings are `level="warning"`.
2. **System prompt injection**: The AI orchestrator (`app/services/ai/chat_orchestrator.py`) injects accessibility guidance into the system prompt, instructing the LLM to: "Always include descriptive alt text for images, use proper heading hierarchy, provide transcript references for media, and use ARIA labels for interactive elements."
3. **Proposal preview**: The proposal response includes an `accessibilityScore` field alongside `validationResult`, allowing the frontend to display a gauge or badge.
4. **Trend tracking**: The system tracks `(model_version, template_type, accessibility_score)` tuples over time so the AI team can measure improvement.

---

### Section 3: API Contracts

#### 3.1 New Endpoint: `POST /api/v1/ai/accessibility/validate`

Validates a course/page/component payload and returns accessibility violations.

**Request:**
```json
{
  "payload": { ... },           // Page data or course data (same shape as validation endpoint)
  "scope": "course|page|component",
  "templateType": "content-text | mcq | ..."
}
```

**Response (200):**
```json
{
  "score": 0.75,
  "pageId": "pg_123",
  "passed": [
    {"check": "alt_text_present", "componentId": "comp_1", "message": "Image has alt text"}
  ],
  "warnings": [
    {"check": "heading_hierarchy", "componentId": "comp_2", "field": "data.content", "message": "Heading order skipped from h1 to h3", "remediation": "Change <h3> to <h2> or insert an <h2>"}
  ],
  "errors": [
    {"check": "alt_text_missing", "componentId": "comp_3", "field": "accessibilityConfig.altText", "message": "Image component 'sales-chart' has no alt text", "remediation": "Provide a descriptive alt text summarizing the chart content"}
  ]
}
```

#### 3.2 Modified: `POST /api/v1/ai/proposals` (proposal creation)

The proposal creation response gains a new field:

```json
{
  "proposalId": "prop_abc123",
  "accessibilityScore": 0.85,
  "accessibilitySummary": {
    "score": 0.85,
    "passed": 8,
    "warnings": 2,
    "errors": 0,
    "detailsUrl": "/api/v1/ai/accessibility/validate?proposalId=prop_abc123"
  },
  "validationResult": { ... }
}
```

#### 3.3 Modified: `POST /api/v1/courses/validate`

The validation result gains accessibility checks as `ValidationError` entries with `category: "accessibility"`:

```json
{
  "valid": true,
  "errors": [],
  "warnings": [
    {
      "id": "a11y-alt-text-missing",
      "field": "pages[0].components[1].accessibilityConfig.altText",
      "category": "accessibility",
      "level": "warning",
      "message": "Component 'header-image' is missing alt text",
      "context": {"remediation": "Add alt text describing the image content"}
    }
  ],
  "timestamp": "2026-06-14T12:00:00Z"
}
```

#### 3.4 New Service Method: `AccessibilityValidator.run()`

```python
class AccessiblityCheckResult(BaseModel):
    check: str
    componentId: Optional[str] = None
    field: str
    message: str
    remediation: str
    severity: Literal["error", "warning"]

class AccessiblityValidationResult(BaseModel):
    score: float
    pageId: Optional[str] = None
    passed: List[AccessiblityCheckResult]
    warnings: List[AccessiblityCheckResult]
    errors: List[AccessiblityCheckResult]
```

---

### Section 4: Database DDL

#### New Table: `accessibility_scores` (tracks scores per page + model)

```sql
CREATE TABLE accessibility_scores (
    id              SERIAL PRIMARY KEY,
    proposal_id     VARCHAR(64) REFERENCES ai_proposals(id) ON DELETE CASCADE,
    course_id       VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    page_id         VARCHAR(100),
    score           NUMERIC(4,3) NOT NULL,          -- 0.000 to 1.000
    total_checks    INTEGER NOT NULL DEFAULT 0,
    passed_checks   INTEGER NOT NULL DEFAULT 0,
    warning_checks  INTEGER NOT NULL DEFAULT 0,
    error_checks    INTEGER NOT NULL DEFAULT 0,
    template_type   VARCHAR(100),
    model_version   VARCHAR(100),                    -- e.g. "claude-sonnet-4-20250514"
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_a11y_scores_course ON accessibility_scores(course_id);
CREATE INDEX idx_a11y_scores_model ON accessibility_scores(model_version);
CREATE INDEX idx_a11y_scores_template ON accessibility_scores(template_type);
```

#### New Table: `accessibility_check_details` (individual check results for audit)

```sql
CREATE TABLE accessibility_check_details (
    id              SERIAL PRIMARY KEY,
    score_id        INTEGER NOT NULL REFERENCES accessibility_scores(id) ON DELETE CASCADE,
    check_name      VARCHAR(64) NOT NULL,            -- e.g. "alt_text_present", "heading_hierarchy"
    component_id    VARCHAR(100),
    field_path      VARCHAR(500),
    severity        VARCHAR(16) NOT NULL,             -- "error", "warning", "pass"
    message         TEXT NOT NULL,
    remediation     TEXT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_a11y_detail_score ON accessibility_check_details(score_id);
CREATE INDEX idx_a11y_detail_check ON accessibility_check_details(check_name);
```

#### Alembic Migration (reference for `alembic/versions/YYYYMMDD_HHMMSS_add_accessibility_tables.py`):

The migration should import `Base` from `app.models.base` and use `op.create_table`, `op.create_index`, and `op.create_foreign_key`. Follow the existing pattern from `20260412_0003_add_export_columns_and_tables.py`.

---

### Section 5: Service Signatures & Implementation

#### 5.1 `app/services/ai/accessibility_validator.py`

```python
"""Accessibility validation for AI-generated course content.

Validates AI-proposed pages/components against WCAG 2.1 AA criteria.
Integrates with the proposal pipeline (US-BKND-AI-008) and the frontend
proposal preview UI.
"""
from __future__ import annotations
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class AccessibilityCheckResult:
    check: str
    component_id: Optional[str] = None
    field: str = ""
    message: str = ""
    remediation: str = ""
    severity: str = "warning"  # "error" | "warning" | "pass"


@dataclass
class AccessibilityValidationResult:
    score: float = 1.0
    page_id: Optional[str] = None
    passed: List[AccessibilityCheckResult] = field(default_factory=list)
    warnings: List[AccessibilityCheckResult] = field(default_factory=list)
    errors: List[AccessibilityCheckResult] = field(default_factory=list)


class AccessiblityValidator:
    """Validates course/page/component data against WCAG 2.1 AA criteria."""

    # Heading tag pattern for content extraction
    _HEADING_RE = re.compile(r"<h([1-6])[^>]*>", re.IGNORECASE)
    _CLICK_HERE_RE = re.compile(
        r"\b(click here|read more|more|here|this link|link)\b", re.IGNORECASE
    )

    def validate(self, payload: Dict[str, Any]) -> AccessibilityValidationResult:
        """Main entry point. Dispatches per-page validation."""
        pages = payload.get("pages", [payload])  # single page or course-shaped
        result = AccessibilityValidationResult()

        for page in pages:
            page_id = page.get("pageId") or page.get("id", "unknown")
            page_result = self._validate_page(page)
            if page_result.errors:
                result.errors.extend(page_result.errors)
            if page_result.warnings:
                result.warnings.extend(page_result.warnings)
            if page_result.passed:
                result.passed.extend(page_result.passed)

        # Aggregate score
        total = len(result.passed) + len(result.warnings) + len(result.errors)
        if total == 0:
            result.score = 1.0
        else:
            result.score = (
                len(result.passed) * 1.0 + len(result.warnings) * 0.5
            ) / total if total > 0 else 1.0

        if len(pages) == 1:
            result.page_id = pages[0].get("pageId") or pages[0].get("id", "unknown")

        return result

    def _validate_page(self, page: Dict[str, Any]) -> AccessibilityValidationResult:
        r = AccessibilityValidationResult()
        r.page_id = page.get("pageId", page.get("id", "unknown"))

        # Check each component
        components = page.get("components") or page.get("templates", [])
        seen_headings: List[int] = []

        for comp in components:
            comp_id = comp.get("componentId") or comp.get("id", "unknown")
            comp_type = comp.get("componentType") or comp.get("type", "unknown")
            data = comp.get("data") or {}
            a11y_config = comp.get("accessibilityConfig") or {}
            style_config = comp.get("styleConfig") or {}

            # Image alt text check
            if comp_type in ("content-image", "infographic", "content-media",
                             "image-hotspots", "hotspot", "carousel"):
                alt = a11y_config.get("altText") or data.get("altText") or ""
                if not alt or not alt.strip():
                    r.errors.append(AccessibilityCheckResult(
                        check="alt_text_missing",
                        component_id=comp_id,
                        field="accessibilityConfig.altText",
                        message=f"Component '{comp_id}' (type={comp_type}) is missing alt text",
                        remediation="Add a descriptive alt attribute that conveys the image content",
                        severity="error",
                    ))
                elif len(alt) < 10:
                    r.warnings.append(AccessibilityCheckResult(
                        check="alt_text_too_short",
                        component_id=comp_id,
                        field="accessibilityConfig.altText",
                        message=f"Component '{comp_id}' alt text is very short ({len(alt)} chars)",
                        remediation="Expand the alt text to meaningfully describe the image",
                        severity="warning",
                    ))
                else:
                    r.passed.append(AccessibilityCheckResult(
                        check="alt_text_present", component_id=comp_id,
                        field="accessibilityConfig.altText",
                        message="Image has descriptive alt text", severity="pass",
                    ))

            # Heading hierarchy check (text content)
            if comp_type in ("content-text", "welcome", "rich-text-editor",
                             "summary", "summary-takeaways"):
                content = data.get("content") or data.get("body") or data.get("htmlContent") or ""
                if isinstance(content, str):
                    headings = self._HEADING_RE.findall(content)
                    if headings:
                        parsed = [int(h) for h in headings]
                        seen_headings.extend(parsed)
                        for i in range(1, len(parsed)):
                            if parsed[i] > parsed[i - 1] + 1:
                                r.warnings.append(AccessibilityCheckResult(
                                    check="heading_hierarchy_skip",
                                    component_id=comp_id,
                                    field="data.content",
                                    message=f"Heading order skips from h{parsed[i-1]} to h{parsed[i]}",
                                    remediation=f"Change the h{parsed[i]} tag to h{parsed[i-1]+1}",
                                    severity="warning",
                                ))

            # Tab/Accordion ARIA check
            if comp_type == "tabs":
                tabs = data.get("tabs") or []
                for ti, tab in enumerate(tabs):
                    tab_a11y = tab.get("accessibilityConfig") or {}
                    if tab_a11y.get("role") != "tabpanel":
                        r.warnings.append(AccessibilityCheckResult(
                            check="tab_aria_role",
                            component_id=comp_id,
                            field=f"data.tabs[{ti}].accessibilityConfig.role",
                            message=f"Tab {ti} is missing role='tabpanel'",
                            remediation="Set accessibilityConfig.role to 'tabpanel' on each tab",
                            severity="warning",
                        ))
                    if not tab_a11y.get("ariaLabel") and not tab.get("title"):
                        r.warnings.append(AccessibilityCheckResult(
                            check="tab_aria_label",
                            component_id=comp_id,
                            field=f"data.tabs[{ti}].accessibilityConfig.ariaLabel",
                            message=f"Tab {ti} has no ariaLabel and no visible title",
                            remediation="Add ariaLabel to each tab button",
                            severity="warning",
                        ))

            if comp_type == "accordion":
                panels = data.get("panels") or []
                for pi, panel in enumerate(panels):
                    panel_a11y = panel.get("accessibilityConfig") or {}
                    if panel_a11y.get("role") != "region":
                        r.warnings.append(AccessibilityCheckResult(
                            check="accordion_aria_role",
                            component_id=comp_id,
                            field=f"data.panels[{pi}].accessibilityConfig.role",
                            message=f"Accordion panel {pi} is missing role='region'",
                            remediation="Set accessibilityConfig.role to 'region' on each panel",
                            severity="warning",
                        ))

            # Transcript check for media
            if comp_type in ("content-video", "video-slide", "audio-player"):
                has_transcript = bool(data.get("transcript")) or bool(
                    a11y_config.get("ariaDescribedBy")
                )
                if not has_transcript:
                    r.warnings.append(AccessibilityCheckResult(
                        check="media_transcript_missing",
                        component_id=comp_id,
                        field="data.transcript",
                        message=f"Media component '{comp_id}' has no transcript reference",
                        remediation="Add a transcript field or link to a transcript-caption component",
                        severity="warning",
                    ))
                else:
                    r.passed.append(AccessibilityCheckResult(
                        check="media_transcript_present", component_id=comp_id,
                        field="data.transcript",
                        message="Media has transcript reference", severity="pass",
                    ))

            # Link purpose check
            if comp_type == "external-link":
                link_text = data.get("title") or data.get("content") or ""
                if self._CLICK_HERE_RE.match(link_text.strip()):
                    r.warnings.append(AccessibilityCheckResult(
                        check="link_purpose_vague",
                        component_id=comp_id,
                        field="data.title",
                        message=f"Link text '{link_text.strip()}' is not descriptive",
                        remediation='Replace vague text like "click here" with descriptive link text',
                        severity="warning",
                    ))

            # Form label check
            if comp_type == "form":
                fields = data.get("fields") or []
                for fi, field in enumerate(fields):
                    field_a11y = field.get("accessibilityConfig") or {}
                    has_label = bool(field.get("label")) or bool(field_a11y.get("ariaLabel"))
                    if not has_label:
                        r.warnings.append(AccessibilityCheckResult(
                            check="form_field_label",
                            component_id=comp_id,
                            field=f"data.fields[{fi}]",
                            message=f"Form field {fi} has no label or ariaLabel",
                            remediation="Add a visible <label> or set accessibilityConfig.ariaLabel",
                            severity="warning",
                        ))

            # Check contrast note on color overrides
            colors = style_config.get("colors") or {}
            if colors and not style_config.get("contrastNote"):
                r.warnings.append(AccessibilityCheckResult(
                    check="color_contrast_note",
                    component_id=comp_id,
                    field="styleConfig.contrastNote",
                    message="Color overrides present but no contrast ratio note",
                    remediation="Add styleConfig.contrastNote with the computed ratio (e.g. '4.5:1')",
                    severity="warning",
                ))

        # Page-level heading validation
        if seen_headings:
            if seen_headings[0] not in (1, 2):
                r.warnings.append(AccessibilityCheckResult(
                    check="first_heading_level",
                    field="page.content",
                    message=f"First heading on page is h{seen_headings[0]}, expected h1 or h2",
                    remediation="Start content with an h1 or h2 heading",
                    severity="warning",
                ))
            r.passed.append(AccessibilityCheckResult(
                check="page_has_headings",
                field="page.content",
                message="Page has structured headings", severity="pass",
            ))
        else:
            r.warnings.append(AccessibilityCheckResult(
                check="page_no_headings",
                field="page.content",
                message="Page has no headings at all",
                remediation="Add at least one h1 or h2 heading for screen-reader navigation",
                severity="warning",
            ))

        return r
```

#### 5.2 `app/services/ai/accessibility_tracker.py` (trend tracking)

```python
"""Tracks accessibility score trends per model and template type."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class AccessiblityTrend:
    model_version: str
    template_type: str
    avg_score: float
    sample_count: int
    last_updated: datetime
```

---

### Section 6: Environment Variables

Add to `.env.example` and `app/db/config.py` documentation:

```
# ============================================
# Accessibility Compliance
# ============================================
# Enable WCAG 2.1 AA accessibility validation in the AI pipeline
ACCESSIBILITY_VALIDATION_ENABLED=true
# Minimum acceptable accessibility score (0.0-1.0) for auto-apply
# Proposals below this threshold require manual review regardless of policy
ACCESSIBILITY_MIN_SCORE_AUTO_APPLY=0.7
# Log every accessibility check result for audit trail
ACCESSIBILITY_AUDIT_ENABLED=true
```

Add to `app/utils/feature_flags.py` flag registry:
```python
'accessibility_validation': FeatureFlag(
    name='accessibility_validation',
    enabled=False,
    description='Enable WCAG 2.1 AA accessibility validation for AI-generated content',
    environments=[Environment.STAGING, Environment.PRODUCTION]
),
```

---

### Section 7: Test Scenarios

#### 7.1 Unit tests (`tests/test_accessibility_validator.py`)

| # | Scenario | Input | Expected Output |
|---|----------|-------|-----------------|
| 1 | Image with alt text | `{"componentType":"content-image","accessibilityConfig":{"altText":"Chart showing Q1 sales"}}` | `passed` includes `alt_text_present` |
| 2 | Image without alt text | `{"componentType":"content-image","accessibilityConfig":{}}` | `errors` includes `alt_text_missing` with remediation |
| 3 | Correct heading hierarchy | `"<h1>Title</h1><h2>Subtopic</h2><h3>Detail</h3>"` | `passed` includes `page_has_headings`, zero warnings on hierarchy |
| 4 | Skipped heading level | `"<h1>Title</h1><h3>Skipped h2</h3>"` | `warnings` includes `heading_hierarchy_skip` |
| 5 | Tab with ARIA role | `{"tabs":[{"title":"Tab1","accessibilityConfig":{"role":"tabpanel","ariaLabel":"Tab 1"}}]}` | `passed` includes `tab_aria_role` |
| 6 | Tab missing ARIA role | `{"tabs":[{"title":"Tab1"}]}` | `warnings` includes `tab_aria_role` and `tab_aria_label` |
| 7 | Media with transcript | `{"componentType":"content-video","data":{"transcript":"Full transcript..."}}` | `passed` includes `media_transcript_present` |
| 8 | Media without transcript | `{"componentType":"content-video","data":{}}` | `warnings` includes `media_transcript_missing` |
| 9 | "Click here" link | `{"componentType":"external-link","data":{"title":"click here"}}` | `warnings` includes `link_purpose_vague` |
| 10 | Link with good text | `{"componentType":"external-link","data":{"title":"View Q3 Financial Report"}}` | No link warning |
| 11 | Form field without label | `{"componentType":"form","data":{"fields":[{"type":"text","name":"email"}]}}` | `warnings` includes `form_field_label` |
| 12 | Form field with ariaLabel | `{"componentType":"form","data":{"fields":[{"type":"text","name":"email","accessibilityConfig":{"ariaLabel":"Email address"}}]}}` | No form warning |
| 13 | Color override without contrast note | `{"styleConfig":{"colors":{"background":"#fff","text":"#333"}}}` | `warnings` includes `color_contrast_note` |
| 14 | Color override with contrast note | `{"styleConfig":{"colors":{"background":"#fff","text":"#333"},"contrastNote":"8.6:1"}}` | No contrast warning |
| 15 | Page with no headings (empty content) | `{"components":[{"componentType":"content-text","data":{"content":""}}]}` | `warnings` includes `page_no_headings` |
| 16 | Empty payload | `{}` | Score = 1.0, zero errors/warnings |
| 17 | Full course with 5 pages, 3 with a11y issues | Course with mixed compliant/non-compliant pages | Aggregate score computed correctly |
| 18 | MCQ without question text | `{"componentType":"mcq","data":{"questions":[{"question":"","options":[]}]}}` | `errors` includes `mcq_empty_question_text` |

#### 7.2 Integration tests (`tests/test_accessibility_integration.py`)

| # | Scenario | Steps | Assertion |
|---|----------|-------|-----------|
| 1 | Proposal created with accessible page | Create AI proposal with compliant page via `POST /api/v1/ai/sessions/{id}/propose` | Response includes `accessibilityScore: 1.0` |
| 2 | Proposal created with inaccessible page | Create AI proposal with image missing alt text | Response includes `accessibilityScore < 1.0` with `errors` array |
| 3 | Validate endpoint returns a11y errors | `POST /api/v1/courses/validate` with course missing alt text | `warnings[]` contains entries with `category: "accessibility"` |
| 4 | System prompt includes accessibility guidance | Inspect system prompt template | Contains sentence about alt text, headings, ARIA labels |
| 5 | Accessibility score persisted after apply | Apply a proposal, then query audit | `accessibility_scores` table has corresponding row |

#### 7.3 Negative / edge tests

| # | Scenario | Expected |
|---|----------|----------|
| 1 | Feature flag disabled | Validator returns empty result (no checks run) |
| 2 | Component with null accessibilityConfig | Treated as missing; appropriate warning/error raised |
| 3 | Very long alt text (500+ chars) | Warning that alt text may be truncated by screen readers |
| 4 | Accordion with 50 panels | All panels checked; performance < 500ms |
| 5 | Course with 0 pages | Score = 1.0, no errors (edge case handled gracefully) |

---

### Section 8: Implementation Tasks

#### Task 35.1 -- Create `AccessibilityValidator` service (3 SP)

- **File:** `app/services/ai/accessibility_validator.py`
- **Details:** Implement the `AccessiblityValidator` class with all WCAG 2.1 AA check methods as specified in Section 5.1.
- **AC:** All 18 unit test scenarios pass.

#### Task 35.2 -- Create DB tables and Alembic migration (2 SP)

- **Files:** `alembic/versions/YYYYMMDD_HHMMSS_add_accessibility_tables.py`, `app/models/accessibility_score.py`
- **Details:** Create `accessibility_scores` and `accessibility_check_details` tables per DDL in Section 4. Create the SQLAlchemy ORM model classes extending `Base`.
- **AC:** Migration runs idempotently; `Base.metadata` includes new tables.

#### Task 35.3 -- Register validator with proposal pipeline (2 SP)

- **File:** `app/routers/ai_proposals.py` (new, part of US-BKND-AI-009)
- **Details:** Call `AccessiblityValidator.validate()` inside the proposal creation handler after schema validation. Merge results into proposal response. Reject proposal if score < `ACCESSIBILITY_MIN_SCORE_AUTO_APPLY` and policy is `auto_apply` (US-BKND-AI-032).
- **AC:** Every proposal response includes `accessibilityScore`.

#### Task 35.4 -- Extend course validation endpoint (1 SP)

- **File:** `app/routers/courses.py` -- the `validate_course()` handler
- **Details:** Call `AccessiblityValidator.validate()` alongside existing validators. Append accessibility results as `ValidationError` entries with `category: "accessibility"`.
- **AC:** `POST /api/v1/courses/validate` returns accessibility warnings.

#### Task 35.5 -- Persist accessibility scores after proposal apply (2 SP)

- **File:** `app/services/ai/accessibility_tracker.py`
- **Details:** After a successful proposal apply, write a row to `accessibility_scores` with score, counts, model version, and template type. Write individual checks to `accessibility_check_details`.
- **AC:** Score record exists for every successfully applied AI proposal.

#### Task 35.6 -- Inject accessibility guidance into system prompt (1 SP)

- **File:** `app/services/ai/chat_orchestrator.py` (part of US-BKND-AI-023)
- **Details:** Add a section to the system prompt template instructing the LLM to: always include alt text, use proper heading hierarchy, provide transcript references, and set ARIA labels.
- **AC:** System prompt contains accessible-content instructions.

#### Task 35.7 -- Add feature flag and env vars (1 SP)

- **Files:** `.env.example`, `app/utils/feature_flags.py`
- **Details:** Register `accessibility_validation` flag. Add env vars `ACCESSIBILITY_VALIDATION_ENABLED`, `ACCESSIBILITY_MIN_SCORE_AUTO_APPLY`, `ACCESSIBILITY_AUDIT_ENABLED`.
- **AC:** Setting `ACCESSIBILITY_VALIDATION_ENABLED=false` skips all a11y checks.

#### Task 35.8 -- Unit and integration tests (3 SP)

- **Files:** `tests/test_accessibility_validator.py`, `tests/test_accessibility_integration.py`
- **Details:** Implement all test scenarios from Section 7.
- **AC:** All tests pass in CI.

**Total estimate: 15 SP**

---

### Key File Paths Summary

| Aspect | Path |
|--------|------|
| Accessibility validator service | `/c/Users/ADMIN/e-learning-backend/app/services/ai/accessibility_validator.py` |
| Score tracking service | `/c/Users/ADMIN/e-learning-backend/app/services/ai/accessibility_tracker.py` |
| Database model (new) | `/c/Users/ADMIN/e-learning-backend/app/models/accessibility_score.py` |
| Alembic migration (new) | `/c/Users/ADMIN/e-learning-backend/alembic/versions/YYYYMMDD_HHMMSS_add_accessibility_tables.py` |
| Proposal router (modified) | `/c/Users/ADMIN/e-learning-backend/app/routers/ai_proposals.py` |
| Course validation endpoint (modified) | `/c/Users/ADMIN/e-learning-backend/app/routers/courses.py` (lines 465-751) |
| Chat orchestrator (modified) | `/c/Users/ADMIN/e-learning-backend/app/services/ai/chat_orchestrator.py` |
| Feature flags (modified) | `/c/Users/ADMIN/e-learning-backend/app/utils/feature_flags.py` (lines 63-66) |
| Environment config (modified) | `/c/Users/ADMIN/e-learning-backend/.env.example` |
| Export contract (referenced) | `/c/Users/ADMIN/e-learning-backend/app/models/export_contract.py` (lines 61-69, `AccessibilityConfig`) |
| Renderer manifest (referenced) | `/c/Users/ADMIN/e-learning-backend/app/services/renderer_manifest.py` (84 template types) |
| Existing export validator (referenced) | `/c/Users/ADMIN/e-learning-backend/app/services/export_validator.py` (lines 293-306, existing accessibility config validation) |
| Existing HTML sanitizer (referenced) | `/c/Users/ADMIN/e-learning-backend/app/services/security/html_sanitizer.py` |
| Alembic env (referenced) | `/c/Users/ADMIN/e-learning-backend/alembic/env.py` |
| Base model (referenced) | `/c/Users/ADMIN/e-learning-backend/app/models/base.py` |
| DB config (referenced) | `/c/Users/ADMIN/e-learning-backend/app/db/config.py` |
| Unit tests (new) | `/c/Users/ADMIN/e-learning-backend/tests/test_accessibility_validator.py` |
| Integration tests (new) | `/c/Users/ADMIN/e-learning-backend/tests/test_accessibility_integration.py` |

---
The enriched epic has been written — 1,567 lines across all 8 sections.

**File:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-036_COST_TRACKING_TOKEN_BUDGET_ENFORCEMENT.md`

**What the epic contains (all 8 sections filled):**

**Section 1 — Functional Specification**
- Three user stories (Platform Operator, Finance Admin, Author)
- Four detailed flows: Request-Level Metering (post-LLM), Budget Check (pre-LLM), Usage Reporting API, Budget Sync Background Job
- 8 actors with defined roles
- Key design decisions (post-billing, cost computed from pricing table, budget overage tolerance, warning headers vs. errors, feature-flagged)

**Section 2 — Technical Design**
- Complete PostgreSQL DDL for 4 new tables: `ai_usage_records`, `ai_usage_aggregates`, `ai_pricing_table`, `ai_budget_config` — with indexes, foreign keys, check constraints, and seed data for 5 Anthropic/OpenAI models
- Full `CostTracker` service class signature with all 10 methods, dataclasses (`UsageRecord`, `BudgetCheckResult`), docstrings, and internal helpers
- 6 API endpoint contracts: `POST /api/v1/ai/chat` (modified), `GET /ai/usage/summary`, `GET /ai/usage/records`, `GET /ai/usage/budget`, `PUT /ai/usage/budget`, `GET /ai/usage/pricing` — with exact request/response JSON
- 10 environment variables with defaults
- Feature flag definition for `cost_tracking`
- Error code table with HTTP status, code, and condition for each failure mode

**Section 3 — Router Implementation**
- Complete `app/routers/ai_usage.py` with admin auth dependency, all 5 endpoints, Pydantic DTOs (`BudgetUpdateDTO`, `UserBudgetOverride`)
- Integration points for modifying `POST /api/v1/ai/chat` to add pre-request `check_budget()` and post-response `record()` calls

**Section 4 — Implementation Plan (9 Tasks)**
1. Alembic migration (full upgrade/downgrade with seed data)
2. SQLAlchemy ORM models (`app/models/ai_usage.py`)
3. `CostTracker` service
4. `BudgetSyncJob` background worker wiring into `app/main.py` lifespan
5. `ai_usage` router
6. AI chat endpoint modifications
7. Feature flag and env vars
8. Prometheus metrics (4 counters/gauges)
9. Test suite

**Section 5 — Security & Operational Considerations**
- Tenant data isolation, pricing table integrity, cost rounding
- 90-day raw retention, monthly partitioning, aggregate immutability
- Budget check performance (single-row lookup), pricing cache TTL

**Section 6 — Test Scenarios (24 tests across 6 groups)**
- Group 1: Usage recording (5 scenarios including unknown model, cache tokens, failure handling)
- Group 2: Budget check (7 scenarios including threshold warnings, exhaustion, unconfigured caps, feature flag)
- Group 3: Usage API endpoints (6 scenarios including pagination, authorization, validation)
- Group 4: Chat endpoint integration (4 scenarios including budget blocked, warning headers, multi-tool turns)
- Group 5: Background sync job (3 scenarios including missing aggregate recovery)
- Group 6: Edge cases (5 scenarios including zero tokens, concurrency, negative tokens)

**Section 7 — Open Questions / Future Considerations**
Prometheus maturity, cache token cost allocation, notification integration, cost-allocation tagging

**Section 8 — Migration Rollback Plan**
5-step rollback: feature flag, env var, alembic downgrade, code revert, pricing table corrections

---
The epic is complete. Here is a summary of what was written.

**File:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-037_TEMPLATE_DEFINITION_HARVESTING.md` (1085 lines)

**8-section content delivered:**

1. **Section 1 -- Title and Metadata**: Epic ID US-BKND-AI-037, priority COULD/SHOULD, depends on US-BKND-AI-011/US-BKND-AI-019/US-BKND-AI-005, references actual codebase files.

2. **Section 2 -- Business Context and User Story**: Identifies the gap between the existing `ImportService._harvest_templates` (operates on `TemplateType` table during SCORM imports only) and the need for a dedicated AI harvest pipeline (operates on `TemplateDefinition` table triggered by proposal apply). Business impact table quantifies time-to-availability improvements.

3. **Section 3 -- Functional Requirements (FR-1 through FR-7)**:
   - FR-1: Three-tier classification pipeline (EXACT_MATCH / NEAR_MATCH / NOVEL)
   - FR-2: Jaccard-like similarity scoring algorithm with field-level diff
   - FR-3: Dual execution modes (synchronous inline, asynchronous via outbox)
   - FR-4: Admin review workflow with preview/edit/publish/merge/reject
   - FR-5: Full provenance tracking schema (session, proposal, course, model, pipeline version)
   - FR-6: Outbox event emission (`TemplateDefinitionHarvested`, `TemplateDefinitionPublished`)
   - FR-7: Harvest report embedded in proposal apply response

4. **Section 4 -- Technical Design and API Contracts**:
   - Full `TemplateHarvester` class in `app/services/ai/template_harvester.py` (400+ lines of implementation-ready Python code)
   - `SchemaSimilarityEngine` with field overlap algorithm
   - New method `get_by_schema_signature_list` on `TemplateDefinitionRepository`
   - Integration hook for proposal apply flow
   - 5 new API endpoints with full request/response schemas (GET pending, GET detail, PATCH publish, DELETE reject, POST merge)
   - DB DDL: 5 new columns on `TemplateDefinition` (`provenance_json`, `harvest_classification`, `harvest_matched_type`, `harvest_similarity`, `review_status`) with complete Alembic migration script
   - 6 environment variables with defaults and descriptions

5. **Section 5 -- Test Scenarios**: 18 unit tests (TH-001 through TH-018), 12 API integration tests (API-TH-001 through API-TH-012), 8 edge cases (EDGE-001 through EDGE-008).

6. **Section 6 -- Acceptance Criteria**: 10 criteria (AC-1 through AC-10) covering novel harvest, deduplication, near-match flagging, admin publish/reject/merge, provenance tracking, graceful failure, and feature flag disable.

7. **Section 7 -- Task Breakdown**: 4 chunks, 19 tasks with file paths, effort estimates, and dependency chains. Chunk 1: Foundation (T1.1-T1.8, 4-5 days). Chunk 2: API and Integration (T2.1-T2.9, 4-5 days). Chunk 3: Admin Review UI and Polish (T3.1-T3.6, 3-4 days). Chunk 4: Outbox Events (T4.1-T4.4, 2-3 days).

8. **Section 8 -- Dependencies and Risks**: 4 dependencies (US-BKND-AI-005, US-BKND-AI-011, US-BKND-AI-019, US-BKND-AI-033) with mitigations. 6 risks scored L/M/H with concrete mitigations. Release criteria across dev/QA/staging/production phases. Full operational runbook with key log lines to monitor.

---
Now I have a thorough understanding of the codebase. Let me compile the complete US-BKND-AI-038 story.

---

**STORY ID:** US-BKND-AI-038  
**TITLE:** SCORM Export Readiness for AI Content  
**EPIC:** AI-Enhanced Content Pipeline  
**ITERATION:** Sprint 9 (AI-integration)  
**STORY POINTS:** 21  
**PRIORITY:** High (blocks AI content authoring integration with LMS delivery)  

---

## 1. DESCRIPTION

As an AI content generator, I need the SCORM export pipeline to correctly serialize AI-authored template data into valid SCORM 1.2 packages so that learning content produced by the AI engine renders identically in an LMS as in the authoring preview, with accurate interaction-tracking metadata in `imsmanifest.xml` and `course_data.js`.

Currently, the SCORM export pipeline (`app/services/scorm_export.py`, `app/routers/export.py`) supports 84 template types registered in `app/services/renderer_manifest.py`, but AI-generated content introduces three new categories not covered by the existing `TEMPLATE_TYPE_ALIASES` mapping, the `_transform_template_data` structural transforms, or the runtime renderer registry embedded in the generated `index.html` player:

1. **Dynamic assessment variants** -- AI can generate `true-false`, `fill-in-blank`, `multiple-select`, `matching`, and `hotspot` question types inside a single `final-assessment` component. The current `course_data.js` renderer registry handles these but the `ScormBehavior` contract in `template_schema.py` does not declare per-question-type SCORM interaction types (`cmi.interactions`), causing `SCORM.recordQuizAnswer()` to log opaque strings instead of standard interaction data.

2. **AI-generated custom component types** -- The AI engine creates ad-hoc template types (e.g., `ai-case-study`, `ai-simulation`, `ai-decision-tree`) that need fallback rendering and alias resolution through the export pipeline. The `_canonicalize_template_type` method and `TEMPLATE_TYPE_ALIASES` dict must be updated to recognize these types.

3. **AI-authored rich-media composites** -- AI content often bundles `text-with-media` with embedded branching rules. The `imsmanifest.xml` generator must declare the correct `adlcp:scormtype="sco"` and the `_generate_items_xml` must include objective metadata for branched paths.

**Acceptance hinges on** the existing `/export/scorm/{courseId}` endpoint producing valid packages that pass LMS import for courses authored through the AI content generation endpoint (`/templates/enhanced/ai/content-generation`).

---

## 2. TECHNICAL DESIGN

### 2a. API Contract Changes

#### POST /export/scorm/{courseId} (enhanced)

**Request body** (new optional fields in `ScormExportRequest`):

```python
# app/routers/export.py

class ScormExportRequest(BaseModel):
    format: Literal["scorm_1_2", "scorm_2004"] = "scorm_1_2"
    includeMedia: bool = True
    # NEW: AI-content export options
    includeAiMetadata: bool = Field(
        default=True,
        description="Include AI generation metadata as SCORM comments"
    )
    interactionLevel: Literal["none", "summary", "detailed"] = Field(
        default="detailed",
        description="Granularity of cmi.interactions data"
    )
    assetInlineThreshold: int = Field(
        default=102_400,  # 100 KB
        ge=0,
        le=1_048_576,
        description="Inline assets smaller than this byte threshold (base64 in course_data.js)"
    )
```

**New response header:**

```
X-Scorm-Capabilities: interactionLevel=detailed;aiMetadata=true;maxInlineAsset=102400
```

**New response codes:**

| Code | Condition |
|------|-----------|
| 422 | AI content validation failed (detail array with new `AI_CONTENT_VALIDATION_ERROR` code) |
| 428 | Course contains AI-generated types requiring a manifest manifest extension not supported by the target LMS (new `LMS_COMPATIBILITY_ERROR`) |

### 2b. Database Migration (Alembic)

File: `alembic/versions/20260614_0001_ai_scorm_readiness.py`

```python
"""Add AI-content SCORM readiness columns.

Revision ID: 20260614_0001
Revises: 20260412_0003
"""

from alembic import op
import sqlalchemy as sa

revision = "20260614_0001"
down_revision = "20260412_0003"

def upgrade():
    # courses: AI-generation fingerprint for export traceability
    op.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS ai_generation_meta JSONB")
    # stores { "model": "gpt-4", "promptVersion": "2.1", "confidence": 0.91,
    #           "generatedAt": "2026-06-14T...", "templateTypes": ["ai-case-study", ...] }

    # templates: per-template AI interaction-level override
    op.execute("ALTER TABLE templates ADD COLUMN IF NOT EXISTS scorm_interaction_type VARCHAR(32)")
    # values: 'choice' | 'fill-in' | 'true-false' | 'matching' | 'none' | NULL

    # export_assets: inline-status cache so AI-authored assets skip re-encoding
    op.execute("ALTER TABLE export_assets ADD COLUMN IF NOT EXISTS inline_threshold INTEGER DEFAULT 102400")
    op.execute("ALTER TABLE export_assets ADD COLUMN IF NOT EXISTS inline_base64 TEXT")

    # New table: AI template type aliases (dynamic, complementing hardcoded TEMPLATE_TYPE_ALIASES)
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_template_aliases (
            id SERIAL PRIMARY KEY,
            source_type VARCHAR(100) NOT NULL UNIQUE,
            target_type VARCHAR(100) NOT NULL,
            transform_strategy VARCHAR(32) NOT NULL DEFAULT 'passthrough',
            schema_signature VARCHAR(64),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_template_aliases_source ON ai_template_aliases (source_type)")

def downgrade():
    op.execute("DROP TABLE IF EXISTS ai_template_aliases")
    op.execute("ALTER TABLE export_assets DROP COLUMN IF EXISTS inline_base64")
    op.execute("ALTER TABLE export_assets DROP COLUMN IF EXISTS inline_threshold")
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS scorm_interaction_type")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS ai_generation_meta")
```

### 2c. New / Modified Service Signatures

#### `app/services/scorm_ai_mapper.py` (NEW)

```python
"""
Maps AI-authored template types to canonical SCORM runtime types
with data-transformation strategies. Reads from ai_template_aliases
table and falls back to the hardcoded TEMPLATE_TYPE_ALIASES dict.

Exposed as a singleton so the export pipeline and the AI content
generation endpoint share the same mapping.
"""

from typing import Dict, List, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.template_type_repo import TemplateTypeRepository


class AiTemplateMapper:
    """
    Resolves AI-generated template types to SCORM runtime types.

    Strategy lookup order:
      1. ai_template_aliases DB table (dynamic, admin-managed)
      2. TemplateTypeRepository aliases (authoring → runtime mappings)
      3. Fallback heuristic (prefix stripping, underscore normalization)
    """

    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._transform_cache: Dict[str, str] = {}

    async def resolve(
        self,
        source_type: str,
        session: Optional[AsyncSession] = None,
    ) -> str:
        """
        Resolve an AI-authored type to its canonical SCORM runtime type.

        Returns the source_type unchanged if no mapping found
        (the caller should then attempt heuristic fallback).

        Raises:
            ValueError: If source_type is empty or None.
        """
        if not source_type or not source_type.strip():
            raise ValueError("source_type must be a non-empty string")

        cached = self._cache.get(source_type)
        if cached:
            return cached

        resolved = await self._resolve_from_db(source_type, session) \
                   or self._resolve_heuristic(source_type)

        self._cache[source_type] = resolved or source_type
        return self._cache[source_type]

    async def get_transform_strategy(
        self,
        source_type: str,
        session: Optional[AsyncSession] = None,
    ) -> str:
        """Return the transform strategy name for the given source type.

        Returns one of: 'passthrough', 'accordion-family', 'tabs-family',
        'stepper-family', 'timeline-family', 'flashcard-family',
        'scenario-family', 'data-viz-family', 'text-with-media-family'.
        Defaults to 'passthrough'.
        """
        if source_type in self._transform_cache:
            return self._transform_cache[source_type]

        strategy = await self._resolve_strategy_from_db(source_type, session)
        if not strategy:
            strategy = self._infer_strategy(source_type)

        self._transform_cache[source_type] = strategy
        return strategy

    async def refresh_cache(self, session: AsyncSession) -> None:
        """Reload all active aliases from the database."""
        repo = TemplateTypeRepository(session)
        aliases = await repo.list_ai_aliases()  # new method
        self._cache.clear()
        self._transform_cache.clear()
        for alias in aliases:
            self._cache[alias.source_type] = alias.target_type
            self._transform_cache[alias.source_type] = alias.transform_strategy

    def _resolve_heuristic(self, source_type: str) -> Optional[str]:
        """Implements fallback heuristics for unregistered types."""
        key = source_type.strip().lower().replace("_", "-")

        # Strip AI prefix
        if key.startswith("ai-"):
            key = key[3:]

        # Map common patterns
        heuristic_map = {
            "simulation": "content-media",
            "guided-exercise": "stepper",
            "knowledge-check": "mcq",
            "reflection": "content-text",
            "glossary": "accordion",
            "faq": "accordion",
        }
        if key in heuristic_map:
            return heuristic_map[key]

        # Strip trailing numbers (e.g., "case-study-v2" → "case-study")
        import re
        base = re.sub(r"-\d+$", "", key)
        if base != key and base in self._cache:
            return self._cache[base]

        return None

    def _infer_strategy(self, source_type: str) -> str:
        """Infer transform strategy from type name."""
        key = source_type.strip().lower()
        if any(x in key for x in ("accordion", "faq", "glossary", "click-reveal")):
            return "accordion-family"
        if any(x in key for x in ("tab", "scenario-debate", "before-after")):
            return "tabs-family"
        if any(x in key for x in ("step", "stepper", "process", "phase")):
            return "stepper-family"
        if any(x in key for x in ("timeline", "cycle", "stage")):
            return "timeline-family"
        if any(x in key for x in ("flashcard", "flip", "card", "micro")):
            return "flashcard-family"
        if any(x in key for x in ("scenario", "branch", "decision", "role")):
            return "scenario-family"
        if any(x in key for x in ("table", "chart", "matrix", "grid", "skill")):
            return "data-viz-family"
        if any(x in key for x in ("media", "image", "video")):
            return "text-with-media-family"
        return "passthrough"
```

#### Modified `SCORMExportService.generate_scorm_package` signature

```python
# New signature in app/services/scorm_export.py

async def generate_scorm_package(
    self,
    course: Course,
    include_assets: bool = True,
    theme_bundle: Optional[Dict[str, Any]] = None,
    # NEW parameters for AI content support
    ai_mapper: Optional[AiTemplateMapper] = None,
    interaction_level: str = "detailed",
    include_ai_metadata: bool = True,
) -> BytesIO:
```

New validation guard to add before the existing production-hardening checks:

```python
# After line 640 in scorm_export.py

# AI content pre-processing: resolve AI-authored template types
if ai_mapper:
    for template in course.templates:
        original_type = template.type
        if original_type and original_type.startswith("ai-"):
            resolved = await ai_mapper.resolve(original_type)
            if resolved != original_type:
                logger.info(
                    "Mapped AI type '%s' → '%s' for template %s",
                    original_type, resolved, template.id,
                )
                template.type = resolved
```

### 2d. New Environment Variables

Add to `.env.example` and `app/db/config.py` environment reader:

```bash
# ── AI SCORM Export Configuration ──────────────────────────────────
SCORM_AI_INTERACTION_LEVEL=detailed      # none | summary | detailed
SCORM_AI_INLINE_ASSET_THRESHOLD=102400   # bytes (100 KB default)
SCORM_AI_INCLUDE_GENERATION_META=true    # embed ai_generation_meta in course_data.js
SCORM_AI_FALLBACK_TEMPLATE_TYPE=content-text  # default fallback for unknown AI types
SCORM_AI_REFRESH_ALIAS_CACHE_INTERVAL=300     # seconds (5 min) between DB alias refreshes
SCORM_MAX_ASSET_INLINE_SIZE=1048576      # 1 MB absolute max for base64 inline
```

Add to `app/db/config.py`:

```python
def get_ai_scorm_config() -> dict:
    return {
        "interaction_level": os.getenv("SCORM_AI_INTERACTION_LEVEL", "detailed"),
        "inline_threshold": int(os.getenv("SCORM_AI_INLINE_ASSET_THRESHOLD", "102400")),
        "include_gen_meta": os.getenv("SCORM_AI_INCLUDE_GENERATION_META", "true").lower() == "true",
        "fallback_type": os.getenv("SCORM_AI_FALLBACK_TEMPLATE_TYPE", "content-text"),
        "alias_cache_interval": int(os.getenv("SCORM_AI_REFRESH_ALIAS_CACHE_INTERVAL", "300")),
        "max_inline_size": int(os.getenv("SCORM_MAX_ASSET_INLINE_SIZE", "1048576")),
    }
```

### 2e. Extended SCORM Interaction Contract for AI Assessments

Modify `app/models/template_schema.py` -- extend `ScormBehavior`:

```python
# In ScormBehavior, add:

# New fields for per-question-type SCORM interaction mapping
question_interaction_map: Optional[Dict[str, str]] = Field(
    default=None,
    description=(
        "Maps question types (mcq|true-false|fill-in-blank|multiple-select|matching) "
        "to SCORM 1.2 interaction types (choice|true-false|fill-in|matching). "
        "Used by AI final-assessment components with mixed question types."
    )
)
ai_confidence_threshold: Optional[float] = Field(
    default=None,
    ge=0.0,
    le=1.0,
    description="Minimum AI confidence to auto-accept this component in export"
)
```

### 2f. AI-Authored Type Registration in `TEMPLATE_TYPE_ALIASES`

Add to the existing dict in `scorm_export.py` (line ~100):

```python
@classmethod
def get_ai_aliases(cls) -> Dict[str, str]:
    """Return AI-prefixed type aliases (loaded from DB + hardcoded defaults)."""
    return {
        # AI content types generated by /templates/enhanced/ai/content-generation
        "ai-case-study": "accordion",
        "ai-simulation": "content-media",
        "ai-decision-tree": "scenario",
        "ai-guided-practice": "stepper",
        "ai-knowledge-check": "mcq",
        "ai-flashcards": "flashcard",
        "ai-timeline": "timeline",
        "ai-comparison": "data-visualization",
        "ai-reflection": "content-text",
        "ai-glossary": "accordion",
        "ai-video-summary": "content-video",
        "ai-interactive-scenario": "branching-scenario",
        "ai-quiz": "final-assessment",
        "ai-mcq": "mcq",
        "ai-true-false": "true-false",
        "ai-fill-blank": "fill-in-blank",
        "ai-multiple-select": "multiple-select",
        "ai-matching": "matching",
        "ai-hotspot": "hotspot",
    }
```

### 2g. Updated `_create_course_data_js` Player Registry

In the `getRenderer` method at line ~1302 of `scorm_export.py`, add AI-fallback renderers:

```javascript
// AI-type fallback renderers (inserted after the 'learning-roadmap' entry)
'ai-case-study':     this.renderAccordion,
'ai-simulation':     this.renderTextWithMedia,
'ai-decision-tree':  this.renderScenario,
'ai-guided-practice': this.renderStepper,
'ai-knowledge-check': this.renderMCQ,
'ai-flashcards':     this.renderFlashcard,
'ai-timeline':       this.renderTimeline,
'ai-comparison':     this.renderDataTable,
'ai-reflection':     this.renderContent,
'ai-glossary':       this.renderAccordion,
'ai-video-summary':  this.renderVideo,
'ai-interactive-scenario': this.renderScenario,
```

### 2h. Updated `imsmanifest.xml` Interaction Metadata

Modify `_create_imsmanifest` to emit AI-specific LOM metadata when `ai_generation_meta` is present on the course record:

```python
# Inside _create_imsmanifest, after line ~753:

if self._include_ai_metadata and hasattr(course, 'ai_generation_meta'):
    ai_meta = course.ai_generation_meta
    manifest_xml = manifest_xml.replace(
        '</lom>',
        f"""        <classification>
            <purpose>
                <source>LOMv1.0</source>
                <value>Educational Objective</value>
            </purpose>
            <description>
                <langstring xml:lang="en">AI-generated content: {ai_meta.get('model', 'unknown')}</langstring>
            </description>
            <keyword>
                <langstring xml:lang="en">AI-generated</langstring>
            </keyword>
        </classification>
        <educational>
            <interactivitytype>
                <source>LOMv1.0</source>
                <value>mixed</value>
            </interactivitytype>
        </educational>
        </lom>""",
        1,
    )
```

---

## 3. VALIDATION RULES

### Pre-Export Validation (add to `ExportValidator.validate`)

```python
# app/services/export_validator.py

def _validate_ai_content(
    self, course_data: Dict[str, Any], course_id: str
) -> None:
    """Validate AI-generated content for SCORM export readiness."""
    pages = course_data.get("pages", [])
    for page in pages:
        for component in page.get("components", []):
            comp_type = component.get("componentType", "")
            if not comp_type.startswith("ai-"):
                continue

            # Rule AI-VAL-001: AI type must be resolvable
            resolved = self.ai_mapper.resolve(comp_type) if self.ai_mapper else None
            if not resolved:
                self.errors.append(ExportValidationError(
                    code="AI_UNRESOLVABLE_TYPE",
                    pagId=page.get("pageId", "?"),
                    componentId=component.get("componentId", "?"),
                    componentType=comp_type,
                    message=f"AI template type '{comp_type}' has no export mapping",
                    details={
                        "courseId": course_id,
                        "availableMappings": list(
                            self.ai_mapper._cache.keys() if self.ai_mapper else []
                        ),
                    }
                ))

            # Rule AI-VAL-002: AI assessment must have interaction config
            data = component.get("data", {})
            if any(qt in comp_type for qt in ["quiz", "assessment", "mcq", "true-false", "fill-blank"]):
                interaction = component.get("interactionConfig")
                if not interaction or not interaction.get("isInteractive", True):
                    self.warnings.append(
                        f"AI component '{component.get('componentId', '?')}' "
                        f"(type: {comp_type}) has no interactionConfig. "
                        f"SCORM tracking will be degraded."
                    )

            # Rule AI-VAL-003: AI branching scenarios must have branch_rules
            if "scenario" in comp_type or "branch" in comp_type:
                has_branching = bool(
                    data.get("branches")
                    or data.get("branchingConfig", {}).get("branches")
                )
                if not has_branching:
                    self.warnings.append(
                        f"AI scenario component '{component.get('componentId', '?')}' "
                        f"(type: {comp_type}) declared as branching but has no branch definitions. "
                        f"Will export as linear content."
                    )

    # Rule AI-VAL-004: AI generation metadata must be present
    ai_meta = course_data.get("ai_generation_meta")
    if self.config.get("include_gen_meta", True) and not ai_meta:
        self.warnings.append(
            "Course has AI-authored components but missing ai_generation_meta. "
            "SCORM packages will lack AI-provenance metadata."
        )
```

### Post-Export Package Validation (add to `_validate_package_structure`)

```python
# In scorm_export.py, _validate_package_structure method

async def _validate_package_structure(self, package_dir: Path) -> None:
    """Production hardening: Validate final package structure."""
    required_files = ["imsmanifest.xml", "index.html", "course_data.js", "scorm_wrapper.js", "styles.css"]
    for file in required_files:
        if not (package_dir / file).exists():
            raise ValueError(f"Missing required file in SCORM package: {file}")

    # NEW: Validate imsmanifest.xml for AI content
    manifest_path = package_dir / "imsmanifest.xml"
    manifest_content = manifest_path.read_text(encoding="utf-8")
    
    # Check well-formed XML (basic)
    if "<?xml" not in manifest_content:
        raise ValueError("imsmanifest.xml is not well-formed XML")
    
    # Check for AI metadata if expected
    if self._include_ai_metadata and "AI-generated" in manifest_content:
        if "classification" not in manifest_content:
            logger.warning(
                "AI metadata flag set but no <classification> element in manifest"
            )

    # Check course_data.js is valid
    data_path = package_dir / "course_data.js"
    data_content = data_path.read_text(encoding="utf-8")
    if "courseData" not in data_content:
        raise ValueError("course_data.js missing courseData variable declaration")

    # Check ZIP size
    zip_size = sum(f.stat().st_size for f in package_dir.rglob("*") if f.is_file())
    max_size = self.max_package_size or 50 * 1024 * 1024
    if zip_size > max_size:
        raise ValueError(f"Package size {zip_size} bytes exceeds limit {max_size} bytes")
    
    logger.info("Package structure validation passed (%d files, %d bytes)",
                 len(list(package_dir.rglob("*"))), zip_size)
```

---

## 4. DB ENTITIES (DDL)

### New Table: `ai_template_aliases`

```sql
CREATE TABLE IF NOT EXISTS ai_template_aliases (
    id              SERIAL PRIMARY KEY,
    source_type     VARCHAR(100) NOT NULL UNIQUE,
    target_type     VARCHAR(100) NOT NULL,
    transform_strategy VARCHAR(32) NOT NULL DEFAULT 'passthrough',
    schema_signature VARCHAR(64),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    updated_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ai_template_aliases_source
    ON ai_template_aliases (source_type);

COMMENT ON TABLE ai_template_aliases IS
    'Dynamic mapping table for AI-authored template types to SCORM runtime types.';
COMMENT ON COLUMN ai_template_aliases.transform_strategy IS
    'One of: passthrough, accordion-family, tabs-family, stepper-family, '
    'timeline-family, flashcard-family, scenario-family, data-viz-family, '
    'text-with-media-family';
```

### New Column: `templates.scorm_interaction_type`

```sql
ALTER TABLE templates
    ADD COLUMN IF NOT EXISTS scorm_interaction_type VARCHAR(32);

COMMENT ON COLUMN templates.scorm_interaction_type IS
    'SCORM 1.2 interaction type override for AI-generated components. '
    'Values: choice | fill-in | true-false | matching | none | NULL';
```

### Seed Data for `ai_template_aliases`

```sql
INSERT INTO ai_template_aliases (source_type, target_type, transform_strategy) VALUES
    ('ai-case-study',           'accordion',            'accordion-family'),
    ('ai-simulation',           'content-media',        'passthrough'),
    ('ai-decision-tree',        'scenario',             'scenario-family'),
    ('ai-guided-practice',      'stepper',              'stepper-family'),
    ('ai-knowledge-check',      'mcq',                  'passthrough'),
    ('ai-flashcards',           'flashcard',            'flashcard-family'),
    ('ai-timeline',             'timeline',             'timeline-family'),
    ('ai-comparison',           'data-visualization',   'data-viz-family'),
    ('ai-reflection',           'content-text',         'passthrough'),
    ('ai-glossary',             'accordion',            'accordion-family'),
    ('ai-video-summary',        'content-video',        'passthrough'),
    ('ai-interactive-scenario', 'branching-scenario',   'scenario-family'),
    ('ai-quiz',                 'final-assessment',     'passthrough'),
    ('ai-mcq',                  'mcq',                  'passthrough'),
    ('ai-true-false',           'true-false',           'passthrough'),
    ('ai-fill-blank',           'fill-in-blank',        'passthrough'),
    ('ai-multiple-select',      'multiple-select',      'passthrough'),
    ('ai-matching',             'matching',             'passthrough'),
    ('ai-hotspot',              'hotspot',              'passthrough')
ON CONFLICT (source_type) DO UPDATE SET
    target_type = EXCLUDED.target_type,
    transform_strategy = EXCLUDED.transform_strategy,
    updated_at = now();
```

---

## 5. ENVIRONMENT VARIABLES

| Variable | Default | Description |
|----------|---------|-------------|
| `SCORM_AI_INTERACTION_LEVEL` | `detailed` | `none` (no interaction tracking), `summary` (lesson_status only), or `detailed` (full cmi.interactions) |
| `SCORM_AI_INLINE_ASSET_THRESHOLD` | `102400` | Assets smaller than this byte threshold are base64-inlined into `course_data.js` instead of packaged as separate files |
| `SCORM_AI_INCLUDE_GENERATION_META` | `true` | When true, embed `ai_generation_meta` into `course_data.js` for runtime provenance |
| `SCORM_AI_FALLBACK_TEMPLATE_TYPE` | `content-text` | Template type used as last resort when AI type resolution and heuristics fail |
| `SCORM_AI_REFRESH_ALIAS_CACHE_INTERVAL` | `300` | Seconds between automatic refresh of `ai_template_aliases` cache (0 = disabled) |
| `SCORM_MAX_ASSET_INLINE_SIZE` | `1048576` | Absolute maximum for base64 inline embedding (1 MB) |
| `AI_TEMPLATE_MAPPER_CACHE_TTL` | `600` | Seconds for the `AiTemplateMapper` in-memory cache TTL |

---

## 6. SERVICE INTERFACE (Python)

### New module: `app/services/scorm_ai_mapper.py`

Full class `AiTemplateMapper` as specified in section 2c above.

### Modified: `app/services/scorm_export.py`

```python
# New constructor parameter
class SCORMExportService:
    def __init__(self, ai_mapper: Optional[AiTemplateMapper] = None):
        self.ai_mapper = ai_mapper or AiTemplateMapper()
        # ... existing init ...

# New method
async def _resolve_ai_templates(
    self, templates: List[Template]
) -> List[Template]:
    """Resolve AI-authored template types to canonical runtime types."""
    resolved = []
    for t in templates:
        if t.type and t.type.startswith("ai-"):
            canonical = await self.ai_mapper.resolve(t.type)
            if canonical and canonical != t.type:
                logger.info("AI type mapped: %s -> %s", t.type, canonical)
                # Shallow-copy to avoid mutating caller's model
                t_copy = t.model_copy(deep=True)
                t_copy.type = canonical
                resolved.append(t_copy)
                continue
        resolved.append(t)
    return resolved
```

### Modified: `app/services/export_validator.py`

```python
# New __init__ parameter
class ExportValidator:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or get_ai_scorm_config()
        self.ai_mapper = AiTemplateMapper()
        self.manifest = get_renderer_manifest()
        # ... existing init ...

# Additionally, the existing component-type validation needs to
# accept AI-prefixed types if they resolve to a known type:
    def _is_supported(self, component_type: str) -> bool:
        canonical = self.ai_mapper.resolve(component_type)  # sync resolve for simple cases
        return self.manifest.is_supported(
            canonical if canonical else component_type
        )
```

### Modified: `app/services/scorm_export_v2.py`

Add the same `ai_mapper` parameter to `SCORMExportServiceV2` for parity:

```python
class SCORMExportServiceV2:
    def __init__(self, ai_mapper: Optional[AiTemplateMapper] = None):
        self.ai_mapper = ai_mapper or AiTemplateMapper()
        # ... existing init ...
```

---

## 7. TEST SCENARIOS

### 7a. Unit Tests (`tests/test_export_ai_readiness.py` -- NEW FILE)

| Test ID | Scenario | Input | Expected Outcome |
|---------|----------|-------|------------------|
| T1 | AI type resolves through `AiTemplateMapper` | `type="ai-case-study"` | Returns `"accordion"` |
| T2 | AI type resolves through DB `ai_template_aliases` | `source_type="ai-decision-tree"` | Returns `"scenario"` |
| T3 | Unknown AI type falls back to heuristic | `type="ai-guided-simulation"` | Returns `"content-media"` (via heuristic) |
| T4 | Unknown AI type with no match returns original | `type="ai-xyz-novel"` | Returns `"ai-xyz-novel"` unchanged |
| T5 | AI type with trailing version resolves | `type="ai-case-study-v2"` | Returns `"accordion"` (strip `-v2`) |
| T6 | Transform strategy is correctly inferred | `type="ai-glossary"` | strategy = `"accordion-family"` |
| T7 | Empty source_type raises ValueError | `""` | `ValueError` raised |
| T8 | Non-AI type passes through unchanged | `type="tabs"` | Returns `"tabs"` |
| T9 | `_resolve_ai_templates` processes list of templates | Mixed list of AI and non-AI types | Only AI-prefixed types remapped |
| T10 | `TEMPLATE_TYPE_ALIASES.get_ai_aliases()` returns dict | N/A | Dict with 19 AI type entries |

### 7b. Integration Tests (`tests/test_export.py` -- EXTEND)

| Test ID | Scenario | Input | Expected Outcome |
|---------|----------|-------|------------------|
| T11 | Export course with AI components | Full course JSON with `ai-case-study` type | ZIP with valid imsmanifest.xml, `ai-case-study` mapped to accordion renderer |
| T12 | Export course with AI final-assessment mixed types | Course with `ai-quiz` containing mcq + true-false + fill-blank questions | `course_data.js` has correct renderer entries, SCORM interactions in `scorm_wrapper.js` |
| T13 | AI content metadata flag on/off | `includeAiMetadata=false` | No `<classification>` element in manifest |
| T14 | Interaction level = "summary" | `interactionLevel=summary` | `course_data.js` skips per-question interaction tracking |
| T15 | Asset inline threshold test | Asset < threshold | base64 in `course_data.js`, no separate file in ZIP |
| T16 | AI type not resolvable returns 422 | Course with unknown AI type | Status 422, code `AI_UNRESOLVABLE_TYPE` |
| T17 | AI interaction config missing returns 422 | `ai-mcq` without `interactionConfig` | Status 422 with warning in detail |
| T18 | AI branching scenario without branches | `ai-decision-tree` without branch definitions | Exports as linear with warning header |
| T19 | `ai_template_aliases` DB seed data | Read from DB | 19 rows returned |
| T20 | `AiTemplateMapper.refresh_cache()` | Call after DB upsert | Cache updated with new mapping |

### 7c. SCORM Package Validation Tests (`tests/test_export_runtime_smoke.py` -- EXTEND)

| Test ID | Scenario | Input | Expected Outcome |
|---------|----------|-------|------------------|
| T21 | AI-generated ZIP imports into SCORM Cloud | Generated ZIP | Imports without error |
| T22 | course_data.js AI content renders in player | AI-authored course | Player renders each AI type without JS error |
| T23 | SCORM interaction data logged for AI assessments | Complete AI quiz | `cmi.interactions.N.id` populated with correct types |
| T24 | imsmanifest.xml validates against SCORM 1.2 XSD | Generated manifest | No schema validation errors |

### 7d. Negative / Edge-Case Tests (`tests/test_export_negative.py` -- EXTEND)

| Test ID | Scenario | Input | Expected Outcome |
|---------|----------|-------|------------------|
| T25 | Course with 100 AI templates | 100 `ai-*` type templates | Exports successfully (within limits) |
| T26 | Course with 101 AI templates | 101 templates | 422 error, exceeds limit |
| T27 | Null `ai_generation_meta` with `includeAiMetadata=true` | Course record with NULL meta | Warning emitted, export proceeds |
| T28 | Circular AI alias | source→target and target→source in DB | Detection + error, fallback to heuristic |
| T29 | Asset exceeds inline threshold | 2 MB asset | Packaged as separate file in ZIP |
| T30 | AI type with non-ASCII characters | `type="ai-cafe-evaluation"` | Resolved via heuristic (strips prefix, normalizes) |

---

## 8. TASK BREAKDOWN

### Task 1: Database Migration (3 SP)
- **Files:** `alembic/versions/20260614_0001_ai_scorm_readiness.py`
- **Deliverables:**
  1. Create migration DDL with all new columns and table
  2. Write `upgrade()` / `downgrade()` functions
  3. Write seed SQL for `ai_template_aliases` table (19 rows)
  4. Add `COMMENT ON` statements for column documentation
  5. Run migration against local and CI databases, verify rollback
- **Acceptance:** `alembic upgrade head` succeeds; `alembic downgrade -1` reverts cleanly; seed data queryable.

### Task 2: Implement `AiTemplateMapper` Service (5 SP)
- **Files:** `app/services/scorm_ai_mapper.py` (NEW), `app/repositories/template_type_repo.py` (add `list_ai_aliases()`)
- **Deliverables:**
  1. Implement `resolve()`, `get_transform_strategy()`, `refresh_cache()` methods
  2. Implement `_resolve_heuristic()` with fallback logic
  3. Implement `_infer_strategy()` with keyword matching
  4. Add `list_ai_aliases()` to `TemplateTypeRepository` (queries `ai_template_aliases` WHERE `is_active=true`)
  5. Wire service into `SCORMExportService.__init__` and `generate_scorm_package`
  6. Wire into `ExportValidator.__init__` for `_validate_ai_content`
  7. Implement configurable TTL cache with `SCORM_AI_REFRESH_ALIAS_CACHE_INTERVAL`
- **Acceptance:** All 10 unit tests (T1-T10) pass.

### Task 3: Update SCORM Export Router and Core Service (4 SP)
- **Files:** `app/routers/export.py`, `app/services/scorm_export.py`, `app/services/scorm_export_v2.py`
- **Deliverables:**
  1. Extend `ScormExportRequest` with AI-specific fields
  2. Add `_resolve_ai_templates()` to `SCORMExportService`
  3. Call `_resolve_ai_templates` inside `generate_scorm_package` before manifest/player generation
  4. Add AI content validation guard (category: AI-VAL-001 through 004) in `validate_for_export`
  5. Extend `imsmanifest.xml` with AI LOM metadata when `includeAiMetadata=true`
  6. Add 19 AI type entries to `getRenderer` registry in `_create_content_html`
  7. Add `X-Scorm-Capabilities` response header
  8. Extend `_validate_package_structure` for AI-specific checks
- **Acceptance:** Integration tests T11-T18 pass.

### Task 4: Extend SCORM Interaction Tracking for AI Assessments (3 SP)
- **Files:** `app/services/scorm_export.py` (the `scorm_wrapper.js` template), `app/services/export_data_builder.py`
- **Deliverables:**
  1. Modify the `scorm_wrapper.js` generated script to support per-question-type interaction types:
     ```javascript
     // In the generated scorm_wrapper.js inside _create_scorm_wrapper
     var interactionTypeMap = {
         'mcq': 'choice',
         'true-false': 'true-false',
         'fill-in-blank': 'fill-in',
         'multiple-select': 'choice',
         'matching': 'matching',
     };
     ```
  2. Update `SCORM.recordQuizAnswer()` in the wrapper to emit `cmi.interactions.N.type` correctly
  3. Update `SCORM.commit()` in the wrapper to set `cmi.core.lesson_status` correctly for AI assessments with mixed question types
  4. Add `interactionLevel` filtering: when `"summary"`, skip per-question interactions and only set `lesson_status`
- **Acceptance:** Test T14 (summary mode), T22 (player rendering), T23 (interaction data) pass.

### Task 5: Update Export Validator with AI Validation Rules (2 SP)
- **Files:** `app/services/export_validator.py`
- **Deliverables:**
  1. Implement `_validate_ai_content()` method with rules AI-VAL-001 through AI-VAL-004
  2. Integrate into `validate()` method
  3. Add `_is_supported()` override that checks AI type resolution
  4. Add comprehensive error codes: `AI_UNRESOLVABLE_TYPE`, `AI_MISSING_INTERACTION`, `AI_MISSING_BRANCHING`, `AI_MISSING_METADATA`
  5. Create helper to return available mappings in error `details`
- **Acceptance:** All validation rules fire correctly in integration test T16.

### Task 6: Write All Tests (3 SP)
- **Files:** `tests/test_export_ai_readiness.py` (NEW), extend `tests/test_export.py`, `tests/test_export_negative.py`, `tests/test_export_runtime_smoke.py`
- **Deliverables:**
  1. 10 unit tests for `AiTemplateMapper`
  2. 8 integration tests for export router with AI content
  3. 4 SCORM package smoke tests for AI-generated packages
  4. 6 negative/edge-case tests
  5. Test fixtures for AI-authored course data
- **Acceptance:** All 28 tests pass in CI; coverage enforces >85% on new code.

### Task 7: Documentation and Config (1 SP)
- **Files:** `.env.example`, `README.md`, inline docstrings
- **Deliverables:**
  1. Document all 7 new environment variables in `.env.example`
  2. Add `ai_scorm_readiness.md` in `docs/` with architecture diagram
  3. Update `app/main.py` startup to pre-warm `AiTemplateMapper` cache
  4. Verify OpenAPI schema auto-generates new `ScormExportRequest` fields
- **Acceptance:** OpenAPI docs at `/docs` show new fields; cache pre-warmer logs success at startup.

---

## DEPENDENCIES

- **Blocks:** US-BKND-AI-039 (SCORM Cloud Integration Testing), US-BKND-AI-041 (AI Content Analytics in LMS)
- **Blocked by:** US-BKND-AI-033 (AI Content Generation Endpoint) -- provides the `ai_generation_meta` payload contract
- **Related:** US-BKND-AI-035 (AI Template Definition Registry), US-BKND-AI-037 (AI Asset Inlining Service)

## RISKS

1. **SCORM 1.2 limitation on interaction types:** The `true-false` interaction response is not part of SCORM 1.2's standard vocabulary list. Mitigation: Map to `choice` with `T`/`F` response labels and document as a SCORM 2004 upgrade item.
2. **Base64 inline bloat:** Very large inlined assets may exceed LMS POST limits for `cmi.comments`. Mitigation: Hard cap at `SCORM_MAX_ASSET_INLINE_SIZE` (1 MB) enforced in `_create_course_data_js`.
3. **Alias cache staleness:** Admin adds new AI alias but the export service misses it. Mitigation: `refresh_cache()` called on each export if `SCORM_AI_REFRESH_ALIAS_CACHE_INTERVAL` seconds have elapsed since last refresh.

---

## RELEVANT FILES

- `C:\Users\ADMIN\e-learning-backend\app\routers\export.py` -- Main export router (existing, to extend)
- `C:\Users\ADMIN\e-learning-backend\app\services\scorm_export.py` -- Primary SCORM export service (existing, to extend)
- `C:\Users\ADMIN\e-learning-backend\app\services\scorm_export_v2.py` -- Refactored v2 service (existing, to extend)
- `C:\Users\ADMIN\e-learning-backend\app\services\export_validator.py` -- Export validation pipeline (existing, to extend)
- `C:\Users\ADMIN\e-learning-backend\app\services\renderer_manifest.py` -- 84-type renderer capability manifest (existing, to reference)
- `C:\Users\ADMIN\e-learning-backend\app\services\export_data_builder.py` -- Canonical export data builder (existing, to reference)
- `C:\Users\ADMIN\e-learning-backend\app\models\export_contract.py` -- Pydantic export contract models (existing, to reference)
- `C:\Users\ADMIN\e-learning-backend\app\models\template_schema.py` -- Template definition schema with ScormBehavior (existing, to extend)
- `C:\Users\ADMIN\e-learning-backend\app\models\persisted_course.py` -- ORM models for courses, templates, export_assets (existing, to extend)
- `C:\Users\ADMIN\e-learning-backend\alembic\versions\20260412_0003_add_export_columns_and_tables.py` -- Previous migration (existing, to reference)
- `C:\Users\ADMIN\e-learning-backend\app\routers\enhanced_templates.py` -- AI content generation endpoint (existing, contract reference)
- `C:\Users\ADMIN\e-learning-backend\app\services\scorm\sanitizers\dynamic_sanitizer.py` -- Data-driven sanitization engine (existing, to reference)
- `C:\Users\ADMIN\e-learning-backend\app\services\scorm\builders\course_data.py` -- Modular course_data builder in v2 architecture (existing, to reference)

---
The complete expanded US-BKND-AI-039 story has been written to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-039_SESSION_CONTEXT_WINDOW_RECOVERY.md`**

Here is a summary of what the story delivers across all 8 sections:

**Section 1 -- Functional Specification:** Four capabilities -- (A) proactive token tracking against configurable thresholds, (B) structured session summary stored in `ai_sessions.summary_json`, (C) transparent context refresh that discards history and injects a compressed summary + rehydration instruction, and (D) user-initiated refresh via a new endpoint. Four detailed flows cover proactive warning, automatic refresh at 95% threshold, emergency recovery from provider `context_length_exceeded`, and manual refresh preserving proposals mid-apply.

**Section 2 -- Technical Specification:**
- **DB DDL:** ALTER TABLE `ai_sessions` with 5 new columns (`summary_json JSONB`, `total_input_tokens BIGINT`, `total_output_tokens BIGINT`, `last_refreshed_at TIMESTAMPTZ`, `refresh_count INTEGER`). New `ai_context_refresh_log` table with 14 columns including trigger_type ENUM, token snapshots, summary, timing, and status.
- **ORM models:** Extended `AISessionRecord` and new `AIContextRefreshRecord` in `app/models/ai_context_refresh.py`.
- **Service signatures:** New `SessionSummaryBuilder` with `build_summary()`, `extract_key_decisions()`, `build_action_timeline()`, `build_summary_message()`, `_compress_summary()`. Enhanced `ChatOrchestrator` with `_check_context_pressure()`, `_refresh_context()`, `_build_rehydrated_context()`, `_handle_context_exceeded_error()`. Enhanced `LLMClient` with `ContextWindowExceededError` classification.
- **API contracts:** `POST /api/v1/ai/sessions/{session_id}/refresh`, `GET /api/v1/ai/sessions/{session_id}/summary`, enhanced `GET /api/v1/ai/sessions/{session_id}/tokens` with `usage_pct` and `status`, enhanced `POST /api/v1/ai/chat` with working `context_refresh` flag.
- **Session summary JSON schema** defined with key_decisions, action_timeline, course_snapshot.
- **Rehydrated context message structure** documented: `[system_prompt, summary_message, rehydration_instruction, user_message]` -- replacing the full conversation history.

**Section 3 -- Non-Functional Requirements:** Performance targets (summary generation < 200 ms p95 deterministic, < 5 s with LLM), security invariants (summary never includes PII, refresh never touches course data), data integrity (summary rebuilt from DB, not LLM output), availability (graceful fallback to simple pruning if summary generation fails, no cascading refreshes).

**Section 4 -- Current State:** Maps exactly what exists from US-BKND-AI-023 (basic pruning, stub summary message, telemetry, session management, unused `context_refresh` field) vs. what is missing (14 specific gaps from running token counters through to frontend indicators).

**Section 5 -- Expansion Points:** LLM-generated NL summaries (gated by `AI_CONTEXT_SUMMARY_USE_LLM`), per-turn token budgets, semantic compression of tool results, predictive context refresh, cross-session carry-over, summary quality monitoring.

**Section 6 -- Validation and Test Scenarios:** 30+ unit tests across 5 test classes (`TestSessionSummaryBuilder`, `TestContextPressureCheck`, `TestContextRefresh`, `TestRehydratedContext`, `TestContextRefreshAPI`), safety invariant tests (refresh never removes proposals, never modifies course data, never loses user messages on provider error), concurrency tests.

**Section 7 -- Definition of Done:** 5 checklists across code, tests, documentation, security, and operational readiness with 40+ specific items.

**Section 8 -- Tasks:** 13 tasks totaling ~48.5 hours estimated effort, from ORM model changes through code review, with clear dependencies mapped to US-BKND-AI-006 and US-BKND-AI-023.

The file is 1856 lines and references actual codebase paths (`app/services/ai/chat_orchestrator.py`, `app/services/ai/llm_client.py`, `app/services/ai/context_builder.py`, `app/models/ai_chat.py`, `app/repositories/ai_chat_repo.py`, `app/routers/ai_chat.py`, `app/routers/ai_chat_dtos.py`, `app/main.py`, `app/models/__init__.py`).

---
The full US-BKND-AI-040 epic has been written to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-040_AI_CONTENT_VERSIONING_ROLLBACK_EPIC.md`**

Here is a summary of what the story delivers across all 8 sections:

**1. Functional Specification** (5 feature groups)
- Course version snapshots on every AI mutation (full or differential)
- Version comparison/diff with page-level and component-level detail
- Point-in-time restore (full-course and single-page) through the standard proposal lifecycle
- Version labeling with unique-per-course labels
- Storage optimization via differential snapshots with configurable full-snapshot intervals
- 15 edge case handlers covering pruned versions, concurrent edits, chain gaps, and quota exhaustion

**2. Technical Specification**
- 3 new DB tables: `ai_version_snapshots`, `ai_version_quotas`, `ai_version_rehydration_cache` with full DDL, constraints, indexes, and GIN indexes on JSONB
- ORM models: `AIVersionSnapshot`, `AIVersionQuota`, `AIVersionRehydrationCache` in `app/models/ai_versioning.py` following existing Mapped/mapped_column patterns
- Pydantic DTOs in `app/models/ai_versioning_dto.py` covering all 13 API surfaces
- 12 API contracts under `/api/v1/ai/admin/courses/{course_id}/versions/*` and `/api/v1/ai/courses/{course_id}/versions` with full request/response examples and error codes
- Service class `VersioningService` in `app/services/ai/versioning_service.py` with 22 method signatures and detailed docstrings
- Repository class `VersionRepository` in `app/repositories/ai_version_repo.py` with cursor pagination, chain walking, quota management, and cache operations
- Alembic migration `20260614_0002` referencing the prior audit migration as parent
- Integration points for `app/main.py`, `alembic/env.py`, `app/models/__init__.py`, and the apply service hook
- 10 new environment variables with documentation

**3. Non-Functional Requirements**
- p95 latency targets for all operations (snapshot creation < 500ms-3s, diff < 2s, rehydration < 3s)
- Storage estimates for 50-page and 500-page courses
- Security (admin-only restore/prune, course isolation, SHA-256 integrity)
- Observability metrics and logging specifications

**4. Current State Assessment** — references existing `CourseRecord`, `PageRecord`, `ComponentRecord`, `ai_audit_logs`, cursor pagination pattern from US-BKND-AI-020, proposal lifecycle from US-BKND-AI-009, apply service from US-BKND-AI-010, and feature flag system

**5. Expansion Points** — version branching, point-in-time recovery, semantic diff, cold storage archival

**6. Validation Strategy** — 35 unit tests, 22 API integration tests, 5 security tests, 5 performance tests with specific scenarios and expected outcomes

**7. Definition of Done** — 16 acceptance criteria, 10 quality gates, 5 signoff roles

**8. Task Breakdown** — 6 task groups totaling 31 story points, with each task listing exact files, implementation details, and test requirements

The story builds directly on US-BKND-AI-010 (apply hook for snapshot creation), US-BKND-AI-009 (proposal lifecycle for restore proposals), and US-BKND-AI-020 (audit linkage for version provenance).

---
The file is complete at 1,846 lines. Here is a summary of what was produced.

**File:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-041_ASYNC_PREVIEW_GENERATION_SERVICE.md`

**Section 1 — Functional Specification** (1.1-1.6): Defines the user stories for both Author and Platform Operator, explains the async preview architecture reusing the existing SCORM renderer pipeline (`app/services/scorm_export.py`, `app/services/scorm/renderers/base.py`, `app/services/scorm/renderers/dynamic.py`), lists actors (Author, AI Agent, Frontend, PreviewGenerationService, Renderer Pipeline, PreviewWorker, DB), and specifies four lifecycle phases (auto-trigger, background rendering, frontend polling, retry/failure). Non-functional requirements table covers render timeout (30s), concurrency (4), P50/P99 latency targets, visual parity with SCORM export, and preview staleness detection.

**Section 2 — API Contract** (2.1-2.5): Four endpoints fully specified:
- `GET /api/v1/ai/proposals/{proposal_id}/preview` — full status + HTML body
- `POST /api/v1/ai/proposals/{proposal_id}/preview/retry` — retry failed preview
- `GET /api/v1/ai/proposals/{proposal_id}/preview/status` — lightweight polling without HTML
- Pydantic response models (`PreviewResponse`, `PreviewStatusResponse`, `PreviewRetryResponse`, `PreviewError`)
- Frontend polling algorithm contract for US-BKND-AI-024

**Section 3 — Database Schema** (3.1-3.3): Alembic migration DDL adding 7 columns to the existing `ai_proposals` table (`preview_html TEXT`, `preview_status VARCHAR(16)`, `preview_error TEXT`, `preview_job_id VARCHAR(64)`, `preview_updated_at TIMESTAMP`, `preview_retry_count INTEGER`, `preview_render_duration_ms INTEGER`) plus an index on `preview_status`. Raw PostgreSQL DDL included for reference.

**Section 4 — Service Signatures** (4.1-4.4): Complete Python code for:
- `PreviewServiceConfig` dataclass
- `PreviewJob` in-memory representation
- `PreviewGenerationService` with `enqueue()`, `get_preview_status()`, `retry()`, `_worker_loop()`, `_render_job()`, `_do_render()`, `_validate_render_output()`, and DB persistence methods
- New `render_single_template()` method on `SCORMExportService`
- Full `ai_preview.py` router with FastAPI endpoint implementations
- Bootstrap wiring for `app/main.py` lifespan, including `get_preview_service()` singleton dependency

**Section 5 — Configuration & Environment Variables**: Seven env vars (`PREVIEW_MAX_CONCURRENCY`, `PREVIEW_RENDER_TIMEOUT_S`, `PREVIEW_MAX_RETRIES`, `PREVIEW_RETRY_DELAY_S`, `PREVIEW_POLL_INTERVAL_MS`, `PREVIEW_MAX_HTML_SIZE`) with defaults and `.env.example` snippet.

**Section 6 — Test Scenarios** (6.1-6.3): Complete pytest test classes covering:
- Unit tests: enqueue and deduplication, status transitions (pending/ready/failed), render timeout enforcement, exception handling, empty HTML validation, missing `data-template-type` validation, retry lifecycle, max retries exhausted, concurrency semaphore enforcement, integration with real `SCORMExportService`
- Integration tests: HTTP 404 for unknown proposals, lightweight status response shape, retry flow, full polling lifecycle
- Renderer parity tests: preview HTML must be a structural subset of full SCORM export HTML (existing `test_accordion_preview_parity.py` extended)

**Section 7 — Task Breakdown** (7.1-7.10): Ten tasks sized with story points and acceptance criteria:
1. DB migration (2hr, 1pt)
2. Pydantic models (1hr, 1pt)
3. PreviewGenerationService core (2-3d, 3pt)
4. Renderer pipeline extension (2-3d, 3pt)
5. Preview API router (1-2d, 2pt)
6. Auto-trigger from proposal handlers (4hr, 1pt)
7. Unit tests (1-2d, 2pt)
8. Integration tests (1d, 2pt)
9. Renderer parity tests (4hr, 1pt)
10. Documentation and configuration (2hr, 1pt)

**Section 8 — Dependencies & References**: Maps six internal dependencies (US-BKND-AI-009, US-BKND-AI-011, US-BKND-AI-024, US-BKND-AI-023, US-BKND-AI-034, US-BKND-AI-029) and lists 14 specific external file references (`app/services/scorm_export.py`, `app/services/scorm/renderers/base.py`, `app/models/course.py`, `tests/test_accordion_preview_parity.py`, etc.) with their purpose.

---
The complete US-BKND-AI-042 user story has been written. Here is a summary of the deliverable.

**File:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-042_SYSTEM_PROMPT_VERSIONING_AB_TESTING.md`

**Size:** 2,136 lines / 91 KB

---

### What the story delivers

**8 full sections following the established template:**

1. **Functional Specification** -- Three primary flows (prompt lifecycle, experiment lifecycle including 4 sub-flows for assignment/resolution/rollback, and variant analytics), plus 10 documented error conditions.

2. **Technical Design** -- Seven new database tables with raw DDL (`ai_prompts`, `ai_prompt_versions`, `ai_prompt_audit`, `ai_experiments`, `ai_experiment_variants`, `ai_experiment_assignments`, `ai_experiment_audit`). Complete SQLAlchemy ORM models. Full Pydantic DTOs. Three service signatures with working Python method stubs:
   - `PromptRegistryService` (8 methods: create, version, activate, render, list, get-with-versions)
   - `ExperimentAssigner` (hash_pct, ff, pct strategies with deterministic user bucketing)
   - `ExperimentRollbackJob` (SQL metric queries for tool_call_error_rate, cost_per_turn, proposal_acceptance_rate)
   - Full API contracts for 12 endpoints across prompt CRUD and experiment lifecycle
   - Integration points into existing `main.py`, US-BKND-AI-023 chat orchestrator, and US-BKND-AI-006 session creation
   - 8 environment variables with defaults
   - Seed data for two default prompts (`course-authoring-default`, `guardrails-default`)
   - Background auto-rollback job with configurable metric thresholds and operator comparison

3. **Non-Functional Requirements** -- Performance targets (p95 latency), security (SHA-256 integrity, immutable versions, audit trails), and data retention policies (90-day assignment cleanup).

4. **Current State** -- Documents that system prompts are currently hardcoded with no versioning, no experiments, and no per-variant analytics.

5. **Expansion Points** -- 8 identified future enhancements (multi-prompt sequencing, automated experiment design, Bayesian analysis, canary rollouts).

6. **Validation and Test Scenarios** -- 20 unit tests (UT-PROMPT-001 through UT-ROLLBACK-003), 6 integration tests, 3 E2E tests, 4 performance tests, and 5 failure scenario specifications.

7. **Definition of Done** -- 16 concrete completion criteria covering database, ORM, services, APIs, integration, seed data, feature flag, and test coverage.

8. **Tasks** -- 35 individual tasks across 7 phases (Database, Prompt Service, Experiment Service, API Endpoints, Orchestrator Integration, Background Jobs, Feature Flag + Docs), totaling 97 story points mapped to a 5-sprint plan.

---

---

# Cross-Cutting Gaps (US-BKND-AI-043 — US-BKND-AI-050)

All 8 sections are present. The user story `US-BKND-AI-043 -- Concurrency Control and Page Locking for AI Sessions` has been written and saved to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-043_CONCURRENCY_CONTROL_PAGE_LOCKING.md`** (1250 lines)

Here is a summary of what was delivered:

**Section 1 -- FUNCTIONAL SPECIFICATION:** 8 numbered functional requirements covering lock acquisition on proposal creation, three lock types (READ/WRITE/SESSION) with a hierarchy, TTL with heartbeat mechanism (15-min default, 5-min heartbeat interval), FIFO conflict queue with notifications, admin lock management endpoints, UI lock visualization, stale lock detection and recovery, and optimistic concurrency for reads via version hashes. Includes full happy-path and error-path user flows.

**Section 2 -- TECHNICAL SPECIFICATION:** Complete API contracts for `POST /api/v1/ai/locks/{lock_id}/heartbeat`, `GET/DELETE /api/v1/ai/locks`, `GET/POST/DELETE /api/v1/ai/locks/queue`, and lock-enriched tool responses. Full DDL for three new tables (`ai_locks`, `ai_lock_queue`, `ai_lock_config`), plus ALTER TABLE statements for `ai_sessions` and `ai_proposals`. Complete `LockManager` service class with all methods. Decorator-based lock middleware (`@with_write_lock`, `@with_read_lock`, `@with_session_lock`). Background `StaleLockScanner` asyncio task. Integration points with US-BKND-AI-006, US-BKND-AI-009, US-BKND-AI-010, US-BKND-AI-011, US-BKND-AI-012, US-BKND-AI-013, US-BKND-AI-023, US-BKND-AI-024, and US-BKND-AI-033.

**Section 3 -- NON-FUNCTIONAL REQUIREMENTS:** Performance targets (<50ms p95 lock acquisition, <30ms p95 heartbeat, 5s full stale scan), security requirements (session auth, admin override header, cross-org isolation, audit events), reliability (survives restart, auto-release within 2x scan interval), scalability (500 concurrent sessions, 5,000 concurrent locks, table partitioning path for scale).

**Section 4 -- CURRENT STATE ASSESSMENT:** Identified that `version_lock.py` exists but is empty, no locking in repositories, no single-session-per-course enforcement, and dual-apply races possible in the current US-BKND-AI-010 proposal pipeline.

**Section 5 -- EXPANSION POINTS:** 4 technical (distributed lock backend via Redis/etcd, lock analytics heatmaps, automatic lock escalation, deadlock detection) and 4 functional (collaborative editing via CRDTs, component-level locking, scheduled lock release, read-only collaboration mode).

**Section 6 -- VALIDATION AND TESTING:** 6 unit tests (acquire/release, write-write conflict, read-read concurrency, write-blocks-read, heartbeat extends TTL, stale detection), 3 integration tests (full lifecycle via API, concurrent session rejection, queue notification), 2 E2E tests (user lock visibility flow, admin force-release flow), and 6 manual QA steps.

**Section 7 -- DEFINITION OF DONE:** 22 checklist items covering database migrations, service implementation, test coverage, API integration, frontend implementation, security review, load testing, and documentation.

**Section 8 -- TASKS AND SUB-TASKS:** 18 tasks in the task table with estimated effort, dependencies, and assignments spanning backend, frontend, QA, and security engineering.

---
Good. 809 lines, all 8 required sections plus the title/metadata section. The user story is complete and has been written to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-044_TWO_TIER_MODEL_ARCHITECTURE.md`**

Here is a summary of what was produced:

---

**US-BKND-AI-044 - Two-Tier Model Architecture: Planner and Generator Separation** (809 lines)

**Section 1 - Functional Specification:**
- User story: Operator wants fast/cheap models for structural planning and premium models for content generation
- 11 functional requirements (FR-PLAN-01 through FR-PLAN-11) covering: tier definition, task-to-tier routing matrix, planner output contract, generator input contract, atomic checkpoints, generator retry without planner re-execution, tier-aware fallback, tier-specific prompt templates, cost attribution per tier, and performance telemetry
- Detailed happy path (single page creation) and 3 error paths (generator validation failure, planner timeout, all planner fallbacks exhausted)
- 4 UI/UX requirements including tier-indicator badges, cost-breakdown widget, admin advanced mode toggle, and end-user transparency

**Section 2 - Technical Specification:**
- Full internal API contracts: `PlannerInput`/`PlannerOutput`/`PlannerResponse`, `GeneratorInput`/`GeneratorResponse`, `TierRoutingRule`/`TierRoutingConfig`, `WorkflowMetrics` Pydantic models
- Complete Python pseudocode for the `generate_page_content()` orchestrator flow
- DDL for 2 new tables (`ai_generation_checkpoints`, `ai_tier_routing_config`) and ALTER TABLE statements for `ai_sessions` and `ai_audit_logs`
- Module tree design with 5 new services (`tier_orchestrator.py`, `planner_service.py`, `generator_service.py`, `checkpoint_service.py`, `tier_routing_config.py`)
- 18 configuration variables with types, defaults, and descriptions
- 9 integration points with existing user stories

**Section 3 - Non-Functional Requirements:**
- 5 performance targets (planner p50 <1.5s, generator p50 <5s, checkpoint write <50ms p99, etc.)
- 4 security requirements (tier isolation, prompt injection boundaries, audit completeness, configuration integrity)
- 4 reliability requirements (checkpoint durability, retry budget exhaustion, crash recovery, tier override coherence)
- 3 scalability requirements (50 concurrent planner invocations, checkpoint cleanup, config cache TTL)

**Section 4 - Current State Assessment:**
- Lists 5 things that exist (US-BKND-AI-026 ModelRouter, US-BKND-AI-023 Chat Orchestrator, existing config variables, proposal persistence, basic telemetry)
- Lists 6 things that must be built (the 5 new services + database migration)
- Lists 5 things that must be modified (model_router.py, cost_tracker.py, context_pruner.py, prompt_manager.py, chat_orchestrator.py)

**Section 5 - Expansion Points:**
- 3 technical: Three-tier architecture (planner + generator + validator), fine-tuned planner model from RLHF data, speculative planning decoding
- 3 functional: per-template-type planner selection, user speed/quality slider, tier cost alerts and quotas

**Section 6 - Validation and Testing:**
- 12 unit tests (UT-PLANNER-01 through UT-METRICS-01) covering planner validation, planner fallback chain, generator retry, checkpoint idempotency, config loading, and metrics collection
- 5 integration tests (IT-PLANNER-GENERATOR-01 through IT-TIER-OVERRIDE-02) covering full two-tier flow, generator retry with validation, crash recovery, tier overrides
- 2 E2E tests (E2E-TIER-01, E2E-TIER-02)
- 5 manual QA steps

**Section 7 - Definition of Done:**
- 18 checklist items covering all schema, services, integrations, tests, and verifications

**Section 8 - Tasks and Sub-Tasks:**
- 12 task rows (T1-T12) with detailed sub-tasks, estimated effort, dependencies, and assigned roles
- Total estimated effort: 21 days

---
The complete user story has been written to:

`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-045_REALTIME_JOB_STATUS_NOTIFICATIONS.md`

Here is a summary of the story's structure and key decisions:

**1. Functional Specification** -- Covers 8 detailed functional requirements:
- FR1: SSE subscription endpoint at `GET /api/v1/events/subscribe`
- FR2: Standardized `JobEvent` JSON schema used by both SSE and polling
- FR3: Unified `useJobNotifications` React hook with dual-channel transport
- FR4: `EventPublisher` backend service for outbox writes and broadcaster signalling
- FR5: `job_events_outbox` table for at-most-once delivery and gap-filling
- FR6: Three visual tiers of progress (compact bar, detail panel, global toast)
- FR7: Complete SSE lifecycle management (heartbeats, reconnection, tab visibility, graceful degradation)
- FR8: Admin dashboard real-time event monitor

Includes full user flows for happy path (SSE), three error paths (SSE failure with polling fallback, backend job failure with retry, page reload with event replay).

**2. Technical Specification** -- Complete with:
- Exact API contracts for all three endpoints (subscribe, poll, unsubscribe) including query parameters, response formats, error codes, and rate limits
- Pydantic `JobEvent` model and TypeScript `JobEvent` interface
- Full DDL for `job_events_outbox` and `sse_subscriptions` tables with 7 indexes and CHECK constraints
- Alembic migration script with upgrade/downgrade
- Module structure (`app/services/events/` with 7 files) including pseudocode for `EventPublisher`, `EventBroadcaster`, and `SSESubscriptionManager`
- 12 configuration variables with sensible defaults

**3. Non-Functional Requirements** -- Performance targets (p50 publish < 10ms, p99 fan-out < 500ms at 1000 connections), security (token-based auth, injection prevention, subscription hijacking prevention), reliability (no event loss across restarts, at-most-once delivery, backpressure with dropped-event recovery), scalability (single-instance for MVP, Redis backplane-ready, 50MB memory budget at 1000 connections).

**4. Current State Assessment** -- Documents what exists (3 separate polling implementations, existing `ImportJob` and `WorkflowJob` models, `sessionStorage` pattern), what must be built (the entire events module and frontend hook), and what must be modified (main.py, orchestrator, preview service, import service, config, 3 frontend files).

**5. Expansion Points** -- 4 technical (Redis backplane, WebSocket upgrade, partitioned outbox, Avro/Protobuf schema registry) and 4 functional (push notifications, per-user preferences, Gantt timeline visualization, automated alerting rules).

**6. Validation and Testing** -- 6 unit tests, 3 integration tests, 2 E2E tests, and 8 manual QA steps, all with detailed pseudocode or procedure.

**7. Definition of Done** -- 20 checklist items covering database, backend services, endpoints, frontend hook, visual components, CI tests, QA signoff, and regression verification.

**8. Tasks and Sub-Tasks** -- 15 task groups (T-001 through T-015) with 40+ sub-tasks, each with estimated hours and clear deliverables. Total estimated effort: approximately 72 hours of engineering work.

---
The user story has been created successfully.

**File**: `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-046_COURSE_LEVEL_OPERATIONS_CREATE_DELETE.md` (1456 lines)

**Structure summary across all 8 sections:**

1. **FUNCTIONAL SPECIFICATION**: User story, 8 numbered FRs (course creation proposal, AI metadata generation, uniqueness validation, course creation apply, deletion proposal, dependency impact analysis, two-phase deletion confirmation, welcome page auto-creation), 4 user flows (happy/error paths for creation and deletion), UI/UX requirements for both creation preview panel and deletion confirmation modal.

2. **TECHNICAL SPECIFICATION**: Complete JSON schemas for 4 new tools (`propose_create_course`, `apply_create_course`, `propose_delete_course`, `confirm_delete_course`) with input/output schemas and error codes. Full DDL for `ai_proposals` table extensions (operation_type, confirmation_phrase_hash, before_snapshot columns). Python service class `CourseOperationsService` with complete method implementations. 5 configuration variables. Integration points matrix across 11 existing services/repositories.

3. **NON-FUNCTIONAL REQUIREMENTS**: Performance targets (p95 latencies: <500ms proposal, <2s create, <1s delete analysis, <5s large delete), security (cryptographic tokens SHA256-stored, typed-phrase confirmation by hash comparison, SERIALIZABLE isolation for deletes), reliability (idempotent apply, transactional rollback, outbox durability), scalability (async delegation for courses >200 pages, rate limiting at 10 creates/s, 2 deletes/min).

4. **CURRENT STATE ASSESSMENT**: 8 existing artifacts identified (CourseRecord, CourseRepository, CRUD routes, PageRecord/ComponentRecord, PageRepository/ComponentRepository, proposal lifecycle, confirmation token system, audit logging). 4 must-create items. 8 must-modify items with exact change descriptions.

5. **EXPANSION POINTS**: 4 technical (async deletion for large courses, course template duplication, soft delete with undo window, batch course creation) and 4 functional (course metadata update via AI, course duplication/renaming, course settings/scoring in creation, AI import from external sources).

6. **VALIDATION & TESTING**: 8 unit tests (UT-1 through UT-8 covering success paths, duplicate detection, welcome page creation, dependency analysis, phrase mismatch, token expiry, full deletion transaction, courseId sanitization). 4 integration tests (create-then-delete lifecycle, duplicate detection, session termination, double-apply idempotency). 2 E2E tests (full lifecycle, stale proposal conflict). 7 manual QA steps.

7. **DEFINITION OF DONE**: 22 checklist items covering all tool registrations, database changes, frontend components, test coverage, regression, system prompt updates, and documentation.

8. **TASKS & SUB-TASKS**: 5 primary tasks (T1-T5) with 22 sub-tasks across Backend Engineer (T1: Course Operations Service, T2: Database Schema), AI Platform Engineer (T3: Tool Registry), Frontend Engineer (T4: UI Components), and QA Engineer (T5: Tests).

---
All 8 sections are present. Here is the summary of the completed user story.

---

**File created:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-047_MULTI_USER_COLLABORATION.md` (1,870 lines)

**US-BKND-AI-047 -- Multi-User Collaboration on AI-Authored Course Content** is a complete, production-grade user story. Here is a summary of what each section contains:

**Section 1 -- Functional Specification (10 FRs):**
- FR-001: Collaboration-aware session model that relaxes the US-BKND-AI-043 SESSION lock to allow multiple concurrent sessions per course
- FR-002: Course collaborator management (invite by email, role assignment, remove, list)
- FR-003: Full permissions matrix for 4 roles (Owner, Editor, Reviewer, Viewer) across all AI operations
- FR-004: Collaborative proposal diffs with ownership, shared "Pending Review" queue
- FR-005: Proposal review and approval workflow (approve, reject, request changes, revise)
- FR-006: Real-time activity feed with 10 event types, persisted and pollable
- FR-007: Session handoff and context transfer across collaborator sessions
- FR-008: Collaboration audit trail extending US-BKND-AI-020 with 7 new event types
- FR-009: Semantic conflict detection and resolution UI at apply time
- FR-010: Per-organization collaboration configuration (6 configurable settings)

Two happy-path user flows (two editors collaborating, reviewer approves editor changes) and one error-path flow (semantic conflict on apply) are provided.

**Section 2 -- Technical Specification:**
- 10 API endpoints with full JSON request/response schemas for invitation management, collaborator management, proposal review, activity feed, session modification, and collaboration configuration
- 5 new database tables DDL (`ai_course_collaborators`, `ai_collaboration_invitations`, `ai_collaboration_activity`, `ai_collaboration_config`, `ai_review_comments`) with indexes and constraints
- 6 existing table modifications (`ai_proposals`, `ai_sessions`, `ai_locks`, `ai_audit_logs`)
- 3 service module designs (`CollaborationService` with 18 methods, `CollaborationMiddleware` with 3 decorators, `CollaborationNotifier` with notification polling)
- Full integration points table mapping to 7 existing US-AI-* stories
- 7 configuration variables

**Section 3 -- Non-Functional Requirements:**
- Performance targets for all collaboration endpoints (p95 under 50-200ms)
- 5 security requirements (server-side role enforcement, invitation token validation, cross-org isolation, session invalidation on removal)
- 4 reliability requirements (state survives restarts, periodic cleanup tasks, graceful degradation when disabled)
- 3 scalability requirements (50 collaborators/course, 10K activity events, 1K concurrent sessions)

**Section 4 -- Current State Assessment:**
- 8 existing items identified (US-BKND-AI-006 sessions, US-BKND-AI-043 locks with SESSION lock restriction, existing collaboration feature flag, social models for student-facing collab, single-author Course model, no user/org ORM models, no review workflow)
- 5 things to build (4 tables, 3 services, API routes, cleanup tasks, frontend components)
- 12 things to modify (session creation, LockManager, proposal lifecycle, audit/outbox, policy engine, frontend AI layer, feature flags)

**Section 5 -- Expansion Points:**
- 4 technical expansions (WebSocket/SSE real-time feed, external user directory, Elasticsearch activity indexing, review SLA enforcement)
- 5 functional expansions (email digests, component-level editing, proposal merge/squash, collaboration templates/presets, lock ownership transfer)

**Section 6 -- Validation and Testing:**
- 6 unit tests with full Python code (invitation lifecycle, role permissions, proposal review cycle, semantic conflict detection, collaborator removal cleanup, activity feed pagination)
- 3 integration tests with full `async_client` code (full workflow via API, concurrent sessions, editor apply blocked without approval)
- 2 E2E test scenarios with step-by-step narrative
- 8 manual QA steps

**Section 7 -- Definition of Done:** 28 checklist items covering database migrations, service implementation, test passing, API completeness, role enforcement, conflict detection, feature flag wiring, security review, performance testing, and regression coverage.

**Section 8 -- Tasks and Sub-Tasks:** 19 tasks with effort estimates (total ~144 hours), dependencies, and assigned roles spanning backend, QA, frontend, and security engineering.

---
All 8 sections are present. The user story has been created successfully.

**File created:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-048_DEAD_LETTER_QUEUE_FAILED_AI_JOB_RECOVERY.md` (2,134 lines)

**Summary of what the story delivers:**

- **Section 1 (Functional Specification):** 10 detailed functional requirements covering automated dead letter capture, failure classification taxonomy (6 categories), advanced DLQ list API with group-by, single-job redrive with input overrides, batch redrive (up to 500 items), failure analysis dashboard (top failure codes, trends, MTTF-P, step-level breakdown), retention/archival, notification integration, user-facing failure visibility, and checkpoint artifact recovery.

- **Section 2 (Technical Specification):** 9 API contracts with full JSON request/response schemas, complete PostgreSQL DDL for `dead_letter_jobs` and `dead_letter_batch_redrives` tables with all indexes (including GIN full-text search), ORM models in SQLAlchemy 2.0 style, dead letter capture service (fire-and-forget hook into the orchestrator), failure classifier (pure function with pattern-matching rules), repository with cursor pagination and aggregation queries, and 12 configuration variables.

- **Section 3 (Non-Functional Requirements):** Performance targets (p95 capture < 500ms, list query < 1s for 100k rows), security (HMAC-signed purge tokens, admin-only access, idempotent redrive), reliability (at-most-once capture, batch partial failure isolation), scalability (up to 1M entries before archival), and retention policies.

- **Section 4 (Current State Assessment):** Detailed analysis of what US-BKND-AI-034 provides, what must be built (7 new files), what must be modified (5 existing files), and key assumptions.

- **Section 5 (Expansion Points):** 4 technical expansions (cold storage archival, ML pattern detection, automated remediation playbooks, Kafka/SNS event stream) and 4 functional expansions (user-initiated redrive requests, scheduled batch redrive, dead letter impact analysis, failure trend alerting).

- **Section 6 (Validation & Testing):** 27 unit tests across 3 test files, 18 integration tests, 3 end-to-end tests, and 6 manual QA steps.

- **Section 7 (Definition of Done):** 16-item checklist covering all functional requirements, quality gates, and compliance criteria.

- **Section 8 (Tasks & Sub-Tasks):** 10 tasks totaling 17 story points, each with specific files, acceptance criteria, and traceability to tests.

---
The user story is complete at 2,333 lines. Here is a summary of the deliverable.

---

**File created:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-049_CONFIRMATION_TOKEN_SYSTEM.md`

**Summary of US-BKND-AI-049 -- Confirmation Token System for Destructive and Irreversible Operations**

This user story defines a centralized, reusable confirmation token system that all destructive/irreversible operations in the AI authoring system must use. It is the **generic foundation** that US-BKND-AI-013 (Delete Page), US-BKND-AI-046 (Course-Level Operations), and US-BKND-AI-029 (Batch Operations) build upon, extracting the inline token logic drafted in US-BKND-AI-013 into a shared service.

Key design decisions:
- **Scope-bound HMAC-SHA256 hashing** instead of bare token SHA256 -- the token is cryptographically bound to the session, proposal, resource type/id, and operation type via `HMAC-SHA256(token + "::" + canonical_scope_string)`. This prevents scope confusion attacks.
- **Plaintext token NEVER persisted** -- only the HMAC-SHA256 hash is stored in `ai_proposals.confirmation_token_sha256`. The plaintext exists only in the propose API response and the frontend's in-memory state.
- **Full validation pipeline** (FR-CT-08) with 10 ordered checks: proposal existence, confirmable state, destructive operation type, user approval, token format, scope-bound hash match, expiry, resource existence, resource hash match, and idempotency.
- **Admin override path** for recovery scenarios, gated behind `AI_ADMIN_CONFIRMATION_BYPASS_ENABLED=false`, with full audit trail and rate limiting.
- **Security event logging** on every token mismatch (brute-force/replay detection).

All 8 required sections are fully populated:
1. **Functional Specification** -- 14 numbered functional requirements (FR-CT-01 through FR-CT-14), 5 user flows (happy + 4 error paths), 6 UI/UX requirements with risk-level matrix
2. **Technical Specification** -- Complete `ConfirmationTokenService` implementation (146 lines of production Python), DDL for extensions, Pydantic DTOs, API contracts with exact JSON schemas, generic confirmation endpoint implementation (100+ lines), integration code for US-BKND-AI-013/US-BKND-AI-046, Alembic migration, ORM model, 6 configuration variables
3. **Non-Functional Requirements** -- 6 performance targets, 10 security requirements, 5 reliability requirements, 4 scalability requirements, 8 observability metrics with Prometheus naming
4. **Current State Assessment** -- 8 items for what exists, 8 items for what must be built, 6 items for what must be modified, 7 dependency references
5. **Expansion Points** -- 4 technical (HSM integration, Redis blacklist, WebAuthn FIDO2, nonce tracking) + 4 functional (soft-delete undo, out-of-band email/SMS, escalation-based, multi-party M-of-N)
6. **Validation and Testing** -- 20 unit tests with full implementations across 5 test classes, 12 integration tests, 4 E2E scenarios (happy path, expiry, conflict, admin override), 5 manual QA steps
7. **Definition of Done** -- 38 checklist items across 6 categories (Code Complete, Tests Pass, Documentation, Security, Operational Readiness, Developer Integration)
8. **Tasks and Sub-Tasks** -- 12 tasks in table format with descriptions, files, acceptance criteria, effort estimates, and dependencies. Total estimated effort: ~35 hours.

---
The user story has been written to `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-BKND-AI-050_STALE_DETECTION_MERGE_RESOLUTION.md` (1,600 lines).

Here is a summary of what was delivered across all 8 sections:

**1. FUNCTIONAL SPECIFICATION** -- 8 numbered functional requirements (FR-001 through FR-008) covering: version hash tracking on all reads, three-level staleness severity classification (STALE_NO_CHANGE, STALE_COMPATIBLE, STALE_CONFLICT), three-way auto-merge for non-conflicting changes, structured conflict reports for conflicting changes, apply-time double-check re-merge, merge audit trail, force override with user confirmation, and staleness for delete/create operations. Three complete user flows (happy path auto-merge, error path conflicting changes, apply-time staleness) plus 5 UI/UX requirements for banners, conflict panels, force-overwrite dialogs, audit views, and admin config.

**2. TECHNICAL SPECIFICATION** -- Complete API contracts with exact JSON schemas for all modified endpoints (fetch_page returns versionHash, propose_update_page accepts versionHash and returns staleInfo, STALE_CONFLICT error with field-level conflict details, APPLY_CONFLICT apply-time error, applied-with-merge response, merge audit query endpoint). DDL for `ai_merge_audit` table (11 columns, 5 indexes, CHECK constraints), `ai_merge_config` table (per-organization merge strategy), and ALTER TABLE on `ai_proposals` (5 new columns). Full Python module signatures for `MergeManager` (50+ lines of class/method signatures with docstrings, dataclasses for FieldConflict, NonConflictingChange, MergeResult, MergeConfig; custom exception classes), `VersionHashRepository` (multi-source BASE state retrieval fallback), and `StaleDetectionMiddleware` (three decorators with integration ordering against US-BKND-AI-043 locks). Integration flow diagrams for proposal creation and apply pipelines annotated with the merge injection points.

**3. NON-FUNCTIONAL REQUIREMENTS** -- 4 performance targets (version hash computation under 10ms p95, three-way merge under 100ms p95, staleness detection under 5ms p95, BASE retrieval under 50ms p95 cached). 4 security requirements (server-authoritative hashing, force-overwrite confirmation enforcement, immutable audit entries, cross-org isolation). 3 reliability requirements (fail-closed on merge service unavailable, BASE retrieval failure fallback to strict mode, merge idempotency). 3 scalability requirements (10,000 lookups/sec for hash-to-state, 1,000 merge events/minute peak, short-lived DB connections).

**4. CURRENT STATE ASSESSMENT** -- Documents 5 existing artifacts (US-BKND-AI-043's version_hash column on ai_proposals but zero merge logic, US-BKND-AI-040's version snapshots as a BASE retrieval fallback, US-BKND-AI-010's apply pipeline with no stale checking, the empty `app/utils/version_lock.py` file, PageRepository with no hash computation). 7 items "must be built" (MergeManager, VersionHashRepository, stale detection middleware, 2 new DB tables + migration, admin merge audit endpoint, merge config endpoint). 10 items "must be modified" (ai_proposals columns, fetch_page handler, all propose_* handlers, all apply handlers, frontend and chat orchestrator).

**5. EXPANSION POINTS** -- 4 technical (semantic conflict detection via component-type plugin system, multi-page batch merge, CRDT-based real-time merge, ML-powered conflict resolution using LLM). 4 functional (component-level merge granularity, scheduled merge policy changes by course lifecycle, user notification preferences, admin merge dry-run preview between version snapshots).

**6. VALIDATION AND TESTING** -- 6 detailed unit tests with full Python code (hash determinism, staleness classification, non-conflicting merge, conflicting rejection, permissive strategy, force-overwrite confirmation). 4 integration tests with full Python code using `async_client` (auto-merge lifecycle, conflict rejection, force overwrite, apply-time staleness). 2 E2E tests with step-by-step browser scenarios (auto-merge with green banner, conflict resolution with three-column panel and confirmation dialog). 8 manual QA steps covering hash visibility, banner appearance, conflict panel layout, confirmation dialog behavior, admin audit filtering, strict mode, apply-time staleness, and cross-org isolation.

**7. DEFINITION OF DONE** -- 25 checklist items covering: database migrations (2 items), service implementation (3 items), tests (3 items), endpoint behavior (5 items), error handling (3 items), audit (2 items), admin API (2 items), frontend (3 items), cross-org isolation (1 item), chat orchestrator integration (1 item), regression (1 item), deployment docs (1 item), security review (1 item).

**8. TASKS AND SUB-TASKS** -- 18 rows in the task table (T-050-01 through T-050-18) covering: DB migration (4h), VersionHashRepository (8h), MergeManager (16h), middleware/decorators (6h), propose handler integration (8h), apply handler integration (6h), fetch_page modification (3h), admin API routes (6h), outbox events (3h), unit tests (8h), integration tests (8h), E2E tests (8h), frontend stale info UI (8h), frontend conflict panel (12h), chat orchestrator integration (6h), performance testing (6h), security review (4h), regression suite (4h). Total estimated effort: **124 hours**.

---