# Functional Requirements Document — Template Marking System

**Document ID:** FRD-TMS-001
**Version:** 1.0
**Date:** 2026-07-11
**Author:** Technical Product Owner (AI-Powered E-Learning Authoring)
**Status:** Draft for Engineering Review
**Approach:** Approach 1 — In-Document Markers (MVP)

---

## 1. Executive Summary

The Template Marking System is a deterministic, marker-based document annotation mechanism that allows authors to embed plain-text structural markers directly into DOCX files before uploading, enabling precise page breakdown, component hierarchy detection, and template type assignment without reliance on heuristic guessing or LLM inference. It addresses the fundamental failure modes of the current ingestion pipeline — page splitting failures, component hierarchy collapse, and template selection misclassification — by giving authors explicit control over document structure through simple bracket-style markers (`[PAGE: tabs]...[/PAGE]`, `[COMPONENT: accordion]...[/COMPONENT]`, `[ITEM: title]...[/ITEM]`). When markers are present, the system routes to a deterministic `MarkedDocumentParser` that constructs a precise structural map before the LLM ever sees the content. When markers are absent, the existing heuristic/LLM pipeline runs completely unchanged.

**Business Value:** The current pipeline (Flow 10/11) achieves 65/82 Postman tests passing, with the 4 Flow 10/11 failures all attributable to breakdown and generation issues. The Template Marking System eliminates these failures entirely for marked documents by (a) reducing page breakdown from a probabilistic LLM operation to a deterministic parse, (b) enabling multi-component pages (accordion panels + content-text intro + key-takeaways callout) instead of flat single-component pages, and (c) removing template selection heuristics entirely — the author specifies the template type explicitly. For unmarked documents, the pipeline is untouched, ensuring zero regression risk. Expected benefits: 100% page boundary accuracy for marked documents, elimination of template selection errors, support for multi-component and nested component pages, reduction in author rework from 3-5 iterations to 1 pass.

**Scope — In Scope:** DOCX plain-text marker detection and parsing, `MarkedDocumentParser` class with `has_markers()`, `parse()`, `validate()` methods, `MarkedDocument`/`MarkedPage`/`MarkedComponent`/`MarkedItem` dataclasses, marker syntax specification with full formal grammar, 14 error codes with structured `ParseError`/`ParseLocation` reporting, integration into the existing pipeline at the ingestion phase (marker detection) and breakdown phase (marker-driven page plan construction), feature flag `AI_TEMPLATE_MARKING_ENABLED` (default: false), additive API changes only (no breaking changes), zero new Python dependencies beyond stdlib.

**Scope — Out of Scope:** PDF marker support (PDF marker detection is a post-MVP expansion), binary or XML-based marker formats (all markers are plain text within paragraph content), marker-aware UI editing tools (the DOCX IS the editing tool), marker insertion/formatting tools within the platform, PPX/XLSX support, markers in non-English content (English only for MVP), custom marker definitions or user-configurable syntax, LLM-based marker generation or repair.

---

## 2. Current State Analysis

### 2.1 The 7-Step Pipeline (Flow 10/11)

The current file-to-course pipeline proceeds through these steps, implemented across the codebase:

**Step 1 — Upload** (`ingestion_service.py:38-183`):
`POST /api/v1/ai/ingestions` creates an `AIIngestionJobRecord`, validates file type/size/SHA-256, saves the file to temp storage. For DOCX files (line 118-127), calls `DocumentExtractor.extract_structured(tmp_path)` which returns structured paragraphs with style metadata. Followed by `DocumentSplitter.split_structured(paragraphs, filename)` which produces flat `Section` objects with `heading`, `content`, `char_count`.

**Step 2 — Extract** (`document_extractor.py:123-218`):
`DocumentExtractor._extract_docx_structured()` iterates `docx.Document.paragraphs`, preserving `style_name`, `text`, `is_heading`, `heading_level` for each paragraph. Output: `{"raw_text": ..., "paragraphs": [...], "table_text": ..., "total_chars": ...}`. This is the raw paragraph data that the `MarkedDocumentParser` will consume.

**Step 3 — Split** (`document_splitter.py:116-170`):
`DocumentSplitter.split_structured()` (line 118) consumes the paragraphs array. It uses REAL heading styles from python-docx to detect section boundaries (line 145: `if para.get("is_heading"):`). Produces flat `Section` objects — each heading and its following body text become one section. No concept of pages. No concept of nested components.

**Step 4 — Breakdown** (`ai_ingestion.py:488-546`):
`_llm_propose_breakdown()` orchestrates three paths:
- **Heuristic path** (`_heuristic_breakdown()`, line 981): Uses regex patterns (`PAGE X —`, `Tab N —`, `Section N —`, `Question N`, lines 1005-1009) to group sections into pages. Template selection via `FeatureDetector` + `TemplateSelector`. Fails for non-standard naming conventions.
- **LLM path** (`_call_llm_for_breakdown()`, line 548): Sends flat section text to an LLM which must GUESS page boundaries from content. Returns JSON array of `{title, template_type, rationale, source_section_ids, order}`.
- **Rule-based path** (`_rule_based_breakdown()`, line 790): One-section-per-page fallback using `_suggest_template()` keyword matching (line 850-866).

**Step 5 — Review** (`ai_ingestion.py:246-311`):
`POST /api/v1/ai/ingestions/{job_id}/review-plan`. Author approves/rejects/modifies the proposed plan. Modifications include retitle, change_template, merge actions (line 1200-1215).

**Step 6 — Generate** (`course_generator.py:529-743`):
`_generate_pages()` iterates the approved plan pages. For each page, dispatches to `_generate_page_content()` (line 749-787) which calls template-specific generators. Each generator produces EXACTLY ONE component (e.g., `_generate_accordion_content` produces one `{"component_type": "accordion", ...}` component). Multi-component pages are partially supported for content-text only (callout + key takeaways, lines 832-865).

**Step 7 — Apply** (`course_generator.py:370-523`):
`apply_generated_course()` creates `CourseRecord` + `PageRecord` + `ComponentRecord` in a single transaction. Pages have `layout.templateType`, components have `component_type`, `data`.

### 2.2 Three Failure Modes

#### Failure Mode 1: Page Splitting Failure

**Root Cause:** `_heuristic_breakdown()` (line 981) uses regex patterns that only match specific naming conventions:
```python
_PARENT_PAGE_RE = re.compile(r'^PAGE\s+\d+\s*[\—\-–]', re.IGNORECASE)  # line 1005
_TAB_CHILD_RE = re.compile(r'^Tab\s+\d+\s*[\—\-–]', re.IGNORECASE)     # line 1006
_SECTION_CHILD_RE = re.compile(r'^Section\s+\d+\s*[\—\-–]', re.IGNORECASE)  # line 1007
```
These patterns ONLY match headings formatted as "PAGE 1 — Title", "Tab 2 — Title", "Section 3 — Title". Real-world DOCX files rarely use this exact convention. `DocumentSplitter` creates sections from ANY heading style — so a DOCX with `Heading 1` for each chapter creates one section per chapter, and `_heuristic_breakdown()` with `max_pages=50` either over-splits (every heading = a page) or under-splits (all content = one page).

**Concrete Example:** A cybersecurity training DOCX with headings "Phishing Attack Vectors", "Social Engineering Techniques", "Knowledge Check — Phishing" and sub-headings "Spear Phishing", "Whaling", "Clone Phishing". The splitter creates 6 flat sections. The breakdown regex matches NONE (no "PAGE X —" prefix). The LLM path must guess boundaries from text — it frequently merges "Spear Phishing" with "Whaling" into a single page, losing the logical tab/accordion structure.

#### Failure Mode 2: Component Hierarchy Failure

**Root Cause:** `_generate_page_content()` (course_generator.py:749) dispatches each page to ONE generator that returns ONE component type. `_generate_tabs_content()` returns a single `{"component_type": "tabs", ...}` (line 951-953). `_generate_accordion_content()` returns a single `{"component_type": "accordion", ...}` (line 908-912). There is NO mechanism to produce a page with an intro content-text component PLUS an accordion component PLUS a key-takeaways callout component. Nested components (tabs where each tab contains content-text + image) are impossible.

**Concrete Example:** A "Phishing Attack Vectors" page should have: (1) a brief content-text introduction, (2) an accordion with items for each attack type, (3) a callout with key takeaways. The current pipeline produces EITHER content-text OR accordion, never both.

#### Failure Mode 3: Template Selection Failure

**Root Cause:** `TemplateSelector` (template_selector.py) uses keyword matching:
```python
_rule_assessment: "quiz", "assessment", "test", "question", "score" → final-assessment (line 71-76)
_rule_tabs: "tab", "compare", "versus", "vs" → tabs (line 110-122)
_rule_accordion: "faq", "question", "answer", "accordion" → accordion (line 125-133)
```
Domain-specific terms like "knowledge check", "scenario exercise", "interactive case study" do NOT match. Content gets wrong template type. Assessment questions get scattered across pages. Accordion-suited content (e.g., "Types of Phishing: Spear Phishing, Whaling, Clone Phishing") gets mapped to content-text because "phishing" is not a keyword.

**Concrete Example:** A section titled "Knowledge Check — Phishing" with 5 MCQ questions should be `final-assessment`. The selector sees "Knowledge Check" which matches NO keyword — it falls through to `content-text` (score 0.40, line 168-171). The 5 MCQs are flattened into prose. The assessment is lost.

### 2.3 Flow 10/11 Postman Failures (from postman_progress.md, lines 123-128)

The 4 Flow 10/11 failures in the Postman collection are:
1. `01-Upload File` — 422 No file attached (test setup issue, not pipeline)
2. `03-Propose Breakdown` — 404 No ingestion job (cascade from #1)
3. `04-Review Plan` — 404 Cascade
4. `06-Poll Status` — 405 Wrong HTTP method (test setup)

While these particular failures are test-setup issues, the underlying pipeline would produce poor results for complex DOCX files due to the three failure modes above. The Template Marking System addresses all three.

---

## 3. Functional Requirements

### FR-1: Marker Detection

**As an** Author, **I want** the system to detect whether my uploaded DOCX contains template markers, **so that** marked documents route to the deterministic marker-based pipeline and unmarked documents continue through the existing pipeline unchanged.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-1-AC1 | Markers detected | A DOCX containing `[PAGE: content-text]` in any paragraph is uploaded | The ingestion job completes extraction | `job.source_metadata.marker_status` is `"detected"` |
| FR-1-AC2 | No markers | A standard DOCX without markers is uploaded | The ingestion job completes extraction | `job.source_metadata.marker_status` is `"absent"` |
| FR-1-AC3 | Mixed content | A DOCX has markers on some pages and plain text on others | `has_markers()` returns true | The document routes to marker pipeline for marked sections |
| FR-1-AC4 | Empty DOCX | A DOCX with no text paragraphs is uploaded | `has_markers()` runs | Returns false, existing pipeline handles it |
| FR-1-AC5 | Performance | A 2000-paragraph DOCX with markers is uploaded | `has_markers()` scans all paragraphs | Returns within 50ms (regex scan only, no parsing) |
| FR-1-AC6 | Backward compat | An unmarked DOCX is uploaded | Pipeline runs to completion | All 834 existing tests pass unchanged |

### FR-2: Page Boundary Markers

**As an** Author, **I want** to mark page boundaries with `[PAGE: template_type]...[/PAGE]`, **so that** each marked page becomes exactly one page in the plan with precise content boundaries.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-2-AC1 | Basic page | A DOCX with `[PAGE: content-text]Content[/PAGE]` | The document is parsed | Exactly 1 `MarkedPage` with `template_type="content-text"` is created |
| FR-2-AC2 | Multiple pages | A DOCX with 5 `[PAGE]...[/PAGE]` blocks | The document is parsed | Exactly 5 `MarkedPage` objects are created in document order |
| FR-2-AC3 | Paragraph attribution | Page 2 spans paragraphs 10-25 | The document is parsed | `page.source_paragraph_indices` = `[10, 11, ..., 25]` |
| FR-2-AC4 | Title attribute | `[PAGE: content-text \| title: My Page Title]` | The document is parsed | `page.title = "My Page Title"` |
| FR-2-AC5 | Order attribute | `[PAGE: tabs \| order: 3]` | The document is parsed | `page.order = 3` |
| FR-2-AC6 | No markers | A DOCX without any `[PAGE]` markers | The document is parsed | Returns `MarkedDocument(has_markers=False)`, empty `pages` list |

### FR-3: Template Type Specification

**As an** Author, **I want** to specify the template type for each page in the marker, **so that** template selection heuristics and LLM calls are bypassed for marked pages.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-3-AC1 | Valid type | `[PAGE: accordion]` | The page is parsed | `page.template_type = "accordion"`. No `TemplateSelector` or LLM is called for this page |
| FR-3-AC2 | Invalid type | `[PAGE: unsupported-type]` | The document is validated | A `ParseError` with code `INVALID_TEMPLATE_TYPE` is returned |
| FR-3-AC3 | Case sensitivity | `[PAGE: Accordion]` | The document is validated | A `ParseError` with code `INVALID_TEMPLATE_TYPE` is returned (case-sensitive) |
| FR-3-AC4 | Mixed pages | Pages 1-3 have markers, page 4 does not | The breakdown runs | Pages 1-3 use their marker types; page 4 goes through `_heuristic_breakdown` |
| FR-3-AC5 | Coverage validation | 5 marked pages + 3 unmarked sections | The page plan is built | Marker mode counts are tracked; coverage validation accounts for both |

### FR-4: Component Specification

**As an** Author, **I want** to mark components within pages with `[COMPONENT: component_type]...[/COMPONENT]`, **so that** each marked component becomes exactly one component in the generated page, preserving order and hierarchy.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-4-AC1 | Single component | `[PAGE: content-text][COMPONENT: content-text]Content[/COMPONENT][/PAGE]` | The page is parsed | 1 `MarkedComponent` with `component_type="content-text"`, `order_index=0` |
| FR-4-AC2 | Multiple components | Same page with 3 `[COMPONENT]` blocks | The page is parsed | 3 `MarkedComponent` objects with `order_index` 0, 1, 2 in document order |
| FR-4-AC3 | Raw content | Text between `[PAGE]` and first `[COMPONENT]` | The page is parsed | `page.raw_content` captures this text |
| FR-4-AC4 | Empty component | `[COMPONENT: content-text][/COMPONENT]` | The document is validated | A `ParseError` with code `EMPTY_COMPONENT` (warning severity) |
| FR-4-AC5 | Visibility attribute | `[COMPONENT: content-text \| visibility: hidden]` | The page is parsed | `component.attributes["visibility"] = "hidden"` |

### FR-5: Component Item Specification

**As an** Author, **I want** to mark items within components using `[ITEM: title]...[/ITEM]`, **so that** accordion panels, tab items, and click-reveal items are created with correct structure and count.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-5-AC1 | Accordion items | `[COMPONENT: accordion][ITEM: Title A]Content A[/ITEM][ITEM: Title B]Content B[/ITEM][/COMPONENT]` | The component is parsed | 2 `MarkedItem` objects with `item_type="accordion-item"`, `title`, `content` |
| FR-5-AC2 | Tab items | `[COMPONENT: tabs]` with 3 `[ITEM: ...]` children | The component is parsed | 3 `MarkedItem` objects with `item_type="tab"` |
| FR-5-AC3 | Click-reveal items | `[COMPONENT: click-reveal]` with 2 `[ITEM: ...]` children | The component is parsed | 2 `MarkedItem` objects with `item_type="reveal-item"` |
| FR-5-AC4 | Order attribute | `[ITEM: Third \| order: 3]`, `[ITEM: First \| order: 1]` | The component is parsed | Items are re-sorted by `order_index` |
| FR-5-AC5 | Missing title | `[ITEM][/ITEM]` | The document is validated | A `ParseError` is generated; the item is still created with empty title |

### FR-6: Assessment Question Markers

**As an** Author, **I want** to mark assessment questions with `[QUESTION: type]...[/QUESTION]`, **so that** each question creates one entry in the final-assessment component with options, correct answer, and feedback.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-6-AC1 | MCQ question | `[QUESTION: mcq]Question text[OPTION: a \| correct: true]Correct[/OPTION][OPTION: b]Wrong[/OPTION][/QUESTION]` | The question is parsed | 1 `MarkedItem` with `item_type="question"`, `metadata.type="mcq"`, 2 options |
| FR-6-AC2 | True-false | `[QUESTION: true-false]Statement[OPTION: a \| correct: true]True[/OPTION][OPTION: b]False[/OPTION][/QUESTION]` | The question is parsed | `metadata.type = "true-false"` |
| FR-6-AC3 | Multi-select | `[QUESTION: multi-select]Select all that apply` with multiple correct options | The question is parsed | `metadata.type = "multi-select"`, multiple options with `correct=true` |
| FR-6-AC4 | Correct answer | `[OPTION: b \| correct: true]` | The question is parsed | `option.metadata.correct = True` |
| FR-6-AC5 | Feedback | `[FEEDBACK]Explanation text[/FEEDBACK]` | The question is parsed | `question.metadata.feedback = "Explanation text"` |
| FR-6-AC6 | No correct answer | A question with no option marked correct | The assessment is validated | A `ParseError` with code `MISSING_CORRECT_ANSWER` |
| FR-6-AC7 | Too few questions | Assessment with only 1 question | The assessment is validated | A `ParseError` with code `TOO_FEW_QUESTIONS` |
| FR-6-AC8 | Passing score attribute | `[COMPONENT: final-assessment \| passing_score: 85]` | The component is parsed | `component.attributes["passing_score"] = 85` |

### FR-7: Nested Component Support

**As an** Author, **I want** to nest components inside other components, **so that** tabs can contain content-text, images, or accordion items within each tab panel.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-7-AC1 | Direct nesting | `[COMPONENT: tabs][ITEM: Tab 1][COMPONENT: content-text]Content[/COMPONENT][/ITEM][/COMPONENT]` | The component tree is parsed | `component.children[0]` is a `MarkedComponent` with `component_type="content-text"` |
| FR-7-AC2 | Two-level max | Three levels of nesting (page > tabs > tabs > content-text) | The document is validated | A `ParseError` with code `MAX_NESTING_EXCEEDED` (default max_nesting=2) |
| FR-7-AC3 | Component order | Nested components appear after the parent's items | The component tree is parsed | `children` list maintains document order |
| FR-7-AC4 | Parent tracking | A nested component's `parent_component_index` | The component tree is parsed | Points to the parent `MarkedComponent`'s index |

### FR-8: Mixed Marked/Unmarked Documents

**As an** Author, **I want** to mark SOME pages while leaving others unmarked, **so that** I can selectively specify structure for complex pages while letting the pipeline handle simple pages.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-8-AC1 | Mixed document | 3 marked pages followed by 2 unmarked sections | The breakdown runs | 3 pages from markers, 2 from heuristic/LLM. Total = 5 |
| FR-8-AC2 | Unmarked between marked | Page 1 marked, 2 unmarked, 3 marked | The breakdown runs | Pages 1 and 3 use markers; page 2 uses existing pipeline |
| FR-8-AC3 | Order preservation | Marked pages at order 0, 4; unmarked at order 1, 2, 3 | The page plan is built | All 5 pages in correct order: 0 (marked), 1-3 (unmarked), 4 (marked) |
| FR-8-AC4 | No duplicate indices | A marked page and an unmarked section both claim order 2 | The page plan is validated | A warning is generated about order conflict |

### FR-9: Parse Error Reporting

**As an** Author, **I want** clear error messages when my markers are malformed, **so that** I can quickly fix the DOCX and re-upload.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-9-AC1 | Structured error | A malformed marker `[PAGE: tabs` (missing closing bracket) | The document is validated | A `ParseError` with code, message, paragraph index, column, severity, suggestion |
| FR-9-AC2 | Error blocks processing | A page with an invalid template type | The job transitions to `marked_parse_error` | User receives error list; no breakdown is proposed |
| FR-9-AC3 | Warning allows processing | An empty `[COMPONENT: content-text]` | The job transitions to `marked_parsed` | Warning is included in response; processing continues |
| FR-9-AC4 | Multiple errors | A document with 5 parse errors | All errors are collected | All 5 are returned in a single response (fail-fast per file, but all errors found in one pass) |
| FR-9-AC5 | Location precision | Error in paragraph 42 | The error is reported | `ParseLocation.paragraph_index = 42`, `context_preview` shows first 100 chars |

### FR-10: Backward Compatibility

**As an** existing user, **I want** to upload unmarked documents exactly as before, **so that** the Template Marking System introduces zero regression risk.

**Acceptance Criteria:**

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| FR-10-AC1 | All 834 tests pass | The repository at known-good commit | All 20 test runners execute | 0 failures, 0 regressions |
| FR-10-AC2 | Postman Flow 10/11 | An unmarked DOCX is uploaded | The full upload-extract-breakdown-generate-apply pipeline runs | All Flow 10/11 Postman tests pass |
| FR-10-AC3 | No API changes | An unmarked document goes through the pipeline | All API responses are inspected | No new fields appear (the new `marker_status` field is absent for unmarked) |
| FR-10-AC4 | Feature flag off | `AI_TEMPLATE_MARKING_ENABLED=false` | A marked DOCX is uploaded | Markers are ignored; existing pipeline handles it |
| FR-10-AC5 | Zero dependencies | The parser is imported | Python environment is checked | No new entries in `requirements.txt` |

---

## 4. Marker Syntax Specification

### 4.1 Page Markers

```
[PAGE: <template_type> [| title: <page_title>] [| order: <n>]]
    ...content and components...
[/PAGE]
```

**Allowed `template_type` values** (case-sensitive, lowercase):
- `content-text` — Rich text page with headings, paragraphs, lists
- `tabs` — Tabbed layout, 2-6 tabs
- `accordion` — Expandable panels, 2-20 items
- `click-reveal` — Interactive reveal elements, 2-10 items
- `final-assessment` — Graded quiz, 3-50 questions
- `welcome` — Course welcome/introduction page
- `summary` — Course section summary page

**Attributes:**
| Attribute | Required | Default | Description |
|-----------|----------|---------|-------------|
| `template_type` | YES | — | One of the 7 allowed values above |
| `title` | No | Derived from first heading or "Untitled Page" | Page title for the plan |
| `order` | No | Sequential (0, 1, 2...) | Explicit page ordering |

**Case Sensitivity:** All marker keyword tokens (`PAGE`, `COMPONENT`, `ITEM`, `QUESTION`, `OPTION`, `FEEDBACK`, `LEARNING_OBJECTIVE`, `KEY_TAKEAWAY`, `CALLOUT`, `[//]`) are CASE-SENSITIVE and must be uppercase. The template_type and attribute values are lowercase. A `[page: content-text]` is NOT a valid PAGE marker — it is treated as literal text.

**Content between markers:** Any text between `[PAGE:` and the first `[COMPONENT:` (or `[/PAGE]` if no components) is captured as `page.raw_content`. This text is passed to the LLM as context for content generation but does NOT create a separate component.

### 4.2 Component Markers

```
[COMPONENT: <component_type> [| order: <n>] [| visibility: <visible|hidden>]]
    ...content and items...
[/COMPONENT]
```

**Allowed `component_type` values** (case-sensitive, lowercase):
- `content-text` — Body text with optional headings
- `tabs` — Tabbed items (requires 2-6 `[ITEM]` children)
- `accordion` — Expandable panels (requires 2-20 `[ITEM]` children)
- `click-reveal` — Click to reveal items (requires 2-10 `[ITEM]` children)
- `final-assessment` — Assessment with questions (requires 3-50 `[QUESTION]` children)

**Nesting Rules:**
- A `[COMPONENT]` can contain other `[COMPONENT]` blocks (nested children)
- Maximum nesting depth: 2 (controlled by `max_nesting` parameter, default 2)
- Depth 1: `[PAGE] > [COMPONENT]`
- Depth 2: `[PAGE] > [COMPONENT: tabs] > [ITEM] > [COMPONENT: content-text]` (nested component inside a tab item)
- Depth 3+ raises `MAX_NESTING_EXCEEDED`

**Raw text inside a component:** Any text between `[COMPONENT:` and the first `[ITEM]` or `[QUESTION]` (or `[/COMPONENT]` if no items) is captured as `component.raw_content`. This text is used by the content generator as the component's content body. For `COMPONENT: content-text`, this IS the content.

### 4.3 Item Markers

```
[ITEM: <item_title> [| order: <n>]]
    ...item content...
[/ITEM]
```

**Usage by component type:**
| Parent Component | Item Type | Required Count |
|-----------------|-----------|----------------|
| `tabs` | `tab` | 2-6 |
| `accordion` | `accordion-item` | 2-20 |
| `click-reveal` | `reveal-item` | 2-10 |

**Content mapping:** The text between `[ITEM:` and `[/ITEM]` maps to the component data field:
- For `tabs`: item content becomes `data.tabs[N].content`
- For `accordion`: item content becomes `data.items[N].content`
- For `click-reveal`: item content becomes `data.items[N].content`

### 4.4 Question Markers

```
[QUESTION: <mcq|true-false|multi-select> [| id: <q_id>]]
    ...question text...
    [OPTION: <id> [| correct: <true|false>]]
        ...option text...
    [/OPTION]
    [FEEDBACK]
        ...feedback text...
    [/FEEDBACK]
[/QUESTION]
```

**Question types:**
| Type | Description | Options Validation |
|------|-------------|-------------------|
| `mcq` | Multiple choice, single correct | Exactly 1 option must have `correct: true` |
| `true-false` | True or false | Exactly 2 options (True/False), 1 correct |
| `multi-select` | Multiple choice, multiple correct | At least 1 option must have `correct: true` |

**Option marker syntax:**
- `[OPTION: <id>]` — Standard option (not correct)
- `[OPTION: <id> | correct: true]` — Correct answer
- `[OPTION: <id> | correct: false]` — Explicitly wrong

**Feedback marker:**
- `[FEEDBACK]...[/FEEDBACK]` — Optional. If absent, a default feedback is generated by the LLM.

**Validation rules:**
- Every `QUESTION` must contain at least 2 `[OPTION]` blocks
- Every assessment `COMPONENT` must contain at least 3 `[QUESTION]` blocks
- Every `mcq` question must have exactly 1 correct option
- Every `true-false` question must have exactly 1 correct option

### 4.5 Special Markers

```
[LEARNING_OBJECTIVE]
    ...objective text...
[/LEARNING_OBJECTIVE]

[KEY_TAKEAWAY]
    ...takeaway text...
[/KEY_TAKEAWAY]

[CALLOUT: <tip|warning|note|important>]
    ...callout text...
[/CALLOUT]
```

**Semantic mapping:**
- `[LEARNING_OBJECTIVE]` — Rendered as a learning objectives callout at the top of the page. Maps to a `content-text` component with CSS class `learning-objective`.
- `[KEY_TAKEAWAY]` — Rendered as a key takeaways summary at the bottom of the page. Maps to a `content-text` component with CSS class `key-takeaway`.
- `[CALLOUT: type]` — Rendered as an inline callout box with the specified style. Maps to a `content-text` component with CSS class `callout-{type}`.

**Placement rules:**
- `[LEARNING_OBJECTIVE]` must appear directly inside `[PAGE]`, not inside a `[COMPONENT]`
- `[KEY_TAKEAWAY]` must appear directly inside `[PAGE]`, not inside a `[COMPONENT]`
- `[CALLOUT]` can appear inside a `[COMPONENT: content-text]` or directly inside `[PAGE]`

### 4.6 Escaping Rules

**Escape character:** Backslash `\`

| Input | Rendered As |
|-------|-------------|
| `\[PAGE: tabs\]` | Literal text `[PAGE: tabs]` — NOT parsed as a marker |
| `\[COMPONENT: accordion\]` | Literal text — NOT parsed as a marker |
| `\\[PAGE: tabs]` | Literal backslash followed by a PAGE marker |
| `Some text \[PAGE\] more text` | "Some text [PAGE] more text" — backslash escapes the bracket |

**Whitespace handling:**
- Leading and trailing whitespace is trimmed from marker content
- Whitespace inside `[` and `]` is normalized: `[PAGE:   tabs]` is valid and equivalent to `[PAGE: tabs]`
- Whitespace on either side of `|` is optional: `[PAGE: tabs|title:My Page]` is valid
- Paragraph breaks within a marker are preserved as part of the content

### 4.7 Comment Markers

```
[//]: # (This is a comment, ignored by parser)
```

**Rules:**
- Comment markers are stripped from the parsed output entirely
- They do not appear in `raw_content` or any attribute
- They can appear anywhere a marker can appear
- They are useful for author notes, version tracking, and inline documentation within the DOCX

---

## 5. MarkedDocumentParser API Specification

### 5.1 Class Definition

```python
class MarkedDocumentParser:
    """Deterministic parser for in-document template markers.

    Scans extracted paragraph data for [PAGE:], [COMPONENT:], [ITEM:],
    [QUESTION:], and special markers. When markers are present, builds
    a structured MarkedDocument tree. When markers are absent, returns
    a MarkedDocument with has_markers=False.

    Uses only stdlib (re, enum, dataclasses) — zero external dependencies.
    """

    def __init__(self, component_registry=None, max_nesting=2):
        """Initialize the parser.

        Args:
            component_registry: Optional dict of valid component types.
                If provided, validates component_type against registry.
                If None, accepts any component_type string.
            max_nesting: Maximum nesting depth for components (default 2).
                Depth 1: PAGE > COMPONENT. Depth 2: PAGE > COMPONENT > COMPONENT.
        """
        pass

    def has_markers(self, paragraphs: list[dict]) -> bool:
        """Scan paragraphs for the presence of any marker syntax.

        Quick scan — runs a single regex over concatenated paragraph text.
        Does NOT parse or validate. Does NOT build the document tree.

        Args:
            paragraphs: List of paragraph dicts from
                DocumentExtractor.extract_structured()["paragraphs"].

        Returns:
            True if any marker syntax is detected. False otherwise.

        Performance: O(n) where n = total characters across all paragraphs.
        Target: < 50ms for 2000 paragraphs (50KB text).

        Edge cases:
            - Empty paragraphs list → False
            - Escaped markers (\[PAGE:) → False (not detected as markers)
            - Comment markers → False (not structural markers)
        """
        pass

    def parse(self, paragraphs: list[dict]) -> MarkedDocument:
        """Parse paragraphs and build a structured MarkedDocument.

        Called AFTER has_markers() returns True, or can be called directly.
        If no markers are found, returns MarkedDocument(has_markers=False).

        Args:
            paragraphs: List of paragraph dicts from
                DocumentExtractor.extract_structured()["paragraphs"].
                Each dict: {"style_name": str, "text": str, "is_heading": bool,
                            "heading_level": int}

        Returns:
            MarkedDocument with pages, components, items fully populated.

        Raises:
            ValueError: If paragraphs is None or not a list.

        Performance: O(n * d) where n = paragraphs, d = nesting depth.
        Target: < 200ms for 2000 paragraphs with 50 pages.

        Error behavior:
            - Malformed markers generate ParseError objects stored in
              MarkedDocument.parse_errors.
            - Parsing continues after errors — all recoverable errors
              are collected in a single pass.
            - Fatal errors (unclosed markers at end of document) stop
              parsing and return partial results.
        """
        pass

    def validate(self, doc: MarkedDocument) -> list[ParseError]:
        """Validate a parsed MarkedDocument against structural and
        business rules.

        Checks performed (in order):
        1. Structural: no overlapping pages, proper nesting, no unclosed markers
        2. Type: valid template_type, valid component_type, valid question_type
        3. Content: assessment has >= 3 questions, tabs has 2-6 items
        4. Cross-reference: no duplicate page titles, unique order indices

        Args:
            doc: A MarkedDocument returned from parse().

        Returns:
            List of ParseError objects. Empty list means valid.

        Performance: O(p) where p = total pages.
        Target: < 50ms for 50 pages.

        Note: Validation is separate from parsing so callers can inspect
        partial parse results even when validation fails.
        """
        pass
```

### 5.2 Input Format

The `paragraphs` parameter is the list of paragraph dicts from `DocumentExtractor.extract_structured()["paragraphs"]` (document_extractor.py:176-180):

```python
[
    {
        "style_name": "Heading 1",        # python-docx style name
        "text": "[PAGE: tabs | title: Phishing Attack Vectors]",  # paragraph text
        "is_heading": True,                # True if style starts with "Heading"
        "heading_level": 1,                # 0=title, 1=Heading1, 2=Heading2, etc.
    },
    {
        "style_name": "Normal",
        "text": "[COMPONENT: content-text]",
        "is_heading": False,
        "heading_level": 0,
    },
    # ... more paragraphs
]
```

### 5.3 Output Format

Returns a `MarkedDocument` dataclass (see Section 6 for full definitions).

### 5.4 Error Conditions

| Condition | Behavior |
|-----------|----------|
| `paragraphs` is None | Raises `ValueError("paragraphs must be a list")` |
| `paragraphs` is empty list | Returns `MarkedDocument(has_markers=False, pages=[])` |
| Malformed marker syntax | Appends `ParseError` to `doc.parse_errors`, continues parsing |
| Unclosed marker at EOF | Appends `ParseError` with code `UNCLOSED_MARKER`, returns partial result |
| No markers found | Returns `MarkedDocument(has_markers=False)` |
| Comment-only document | Returns `MarkedDocument(has_markers=True, pages=[])` (markers exist but no structural content) |

### 5.5 Performance Characteristics

| Scenario | Target | Measurement |
|----------|--------|-------------|
| `has_markers()` on 2000 paragraphs (50KB) | < 50ms | Wall clock |
| `parse()` on 2000 paragraphs with 50 pages | < 200ms | Wall clock |
| `validate()` on 50-page document | < 50ms | Wall clock |
| Memory for 50-page, 150-component document | < 5MB | process.memory_info().rss delta |
| Memory for 2000-paragraph, no-marker document | < 1MB | process.memory_info().rss delta |

---

## 6. Data Structures

### 6.1 MarkedDocument

```python
@dataclass
class MarkedDocument:
    """Top-level result of parsing a document for template markers.

    When has_markers is True, the document structure is fully represented
    by pages, components, and items. Unmarked_paragraphs contains any
    paragraphs that fall outside all marker boundaries (text before the
    first [PAGE], between [/PAGE] and the next [PAGE], or after the last
    [/PAGE]).
    """
    has_markers: bool = False
    """True if any marker syntax was detected and parsed."""

    source_filename: str = ""
    """Original filename from the ingestion job."""

    pages: list[MarkedPage] = field(default_factory=list)
    """All marked pages in document order. Empty if has_markers is False."""

    unmarked_paragraphs: list[dict] = field(default_factory=list)
    """Paragraphs not inside any marker boundary. These are passed to the
    existing heuristic/LLM pipeline for page breakdown."""

    parse_errors: list[ParseError] = field(default_factory=list)
    """Errors collected during parsing. Empty means clean parse."""

    warnings: list[str] = field(default_factory=list)
    """Non-blocking warnings."""

    metadata: dict = field(default_factory=dict)
    """Summary metadata. Always includes:
        - marker_count: total number of markers found
        - page_count: len(pages)
        - component_count: total across all pages
        - item_count: total across all components
        - parse_duration_ms: wall clock time for parse()
    """
```

### 6.2 MarkedPage

```python
@dataclass
class MarkedPage:
    """A single page defined by [PAGE: ...] ... [/PAGE] markers."""

    title: str = ""
    """Page title from the 'title' attribute, or derived from first heading."""

    template_type: str = "content-text"
    """Template type from the PAGE marker. Must be one of:
    content-text, tabs, accordion, click-reveal, final-assessment, welcome, summary."""

    order: int = 0
    """Page order from the 'order' attribute, or sequential index."""

    components: list[MarkedComponent] = field(default_factory=list)
    """Top-level components within this page, in document order."""

    source_paragraph_indices: list[int] = field(default_factory=list)
    """Indices into the original paragraphs list that fall within
    this page's [PAGE]...[/PAGE] boundary."""

    raw_content: str = ""
    """Text content between [PAGE: ...] and the first [COMPONENT: ...]
    or [/PAGE]. Used as context for LLM content generation."""

    attributes: dict = field(default_factory=dict)
    """All attributes from the PAGE marker:
        - title (str)
        - order (int)
        - Any custom attributes
    Always includes 'template_type' and 'title'."""

    learning_objectives: list[str] = field(default_factory=list)
    """Learning objectives from [LEARNING_OBJECTIVE] markers within this page."""

    key_takeaways: list[str] = field(default_factory=list)
    """Key takeaways from [KEY_TAKEAWAY] markers within this page."""
```

### 6.3 MarkedComponent

```python
@dataclass
class MarkedComponent:
    """A single component defined by [COMPONENT: ...] ... [/COMPONENT] markers."""

    component_type: str = "content-text"
    """Component type from the COMPONENT marker."""

    order_index: int = 0
    """Order within the parent. Derived from 'order' attribute or sequential."""

    items: list[MarkedItem] = field(default_factory=list)
    """Items within this component ([ITEM] markers). Populated for
    tabs, accordion, click-reveal components."""

    children: list[MarkedComponent] = field(default_factory=list)
    """Nested components. Depth is limited by max_nesting."""

    raw_content: str = ""
    """Text content between [COMPONENT: ...] and the first child marker
    or [/COMPONENT]. For content-text, this IS the component content."""

    source_paragraph_indices: list[int] = field(default_factory=list)
    """Indices into the original paragraphs list."""

    attributes: dict = field(default_factory=dict)
    """All attributes from the COMPONENT marker:
        - order (int)
        - visibility (str): "visible" or "hidden"
        - passing_score (int): for final-assessment only
    """

    parent_page_index: int = -1
    """Index into MarkedDocument.pages. -1 if not yet assigned."""

    parent_component_index: int = -1
    """Index into the parent component's children list. -1 if top-level."""

    callouts: list[dict] = field(default_factory=list)
    """Callouts from [CALLOUT: type] markers within this component.
    Each dict: {"type": str, "content": str, "source_paragraph_indices": list[int]}"""
```

### 6.4 MarkedItem

```python
@dataclass
class MarkedItem:
    """A single item within a component, defined by [ITEM: ...] ... [/ITEM] markers."""

    title: str = ""
    """Item title from the ITEM marker's attribute."""

    content: str = ""
    """Item content between [ITEM: ...] and [/ITEM]."""

    item_type: str = "tab"
    """Derived from parent component:
        - "tab" for tabs components
        - "accordion-item" for accordion components
        - "reveal-item" for click-reveal components
        - "question" for [QUESTION] markers
        - "option" for [OPTION] markers within questions
        - "feedback" for [FEEDBACK] markers within questions
    """

    order_index: int = 0
    """Order within the parent component."""

    metadata: dict = field(default_factory=dict)
    """Type-specific metadata:
        For questions:
            - question_type: "mcq" | "true-false" | "multi-select"
            - id: str (question ID)
            - correct_answer: str | bool (resolved correct value)
            - feedback: str (feedback text)
        For options:
            - correct: bool (whether this is the correct answer)
            - id: str (option ID)
        For items:
            - (no additional metadata beyond title/content)
    """

    source_paragraph_indices: list[int] = field(default_factory=list)
    """Indices into the original paragraphs list."""

    children: list | None = None
    """Optional list of MarkedComponent children (for nested items within
    a tab/accordion panel). Populated only when the ITEM contains
    [COMPONENT: ...] markers within it."""
```

### 6.5 ParseError

```python
@dataclass
class ParseError:
    """A structured error or warning from marker parsing or validation."""

    code: str = ""
    """Error code string. See Section 10 for all codes."""

    message: str = ""
    """Human-readable error description. Should tell the author what
    went wrong in plain language."""

    location: ParseLocation = field(default_factory=lambda: None)
    """Where the error occurred. None for document-level errors."""

    severity: str = "error"
    """"error" — blocks processing. "warning" — allows processing."""

    suggestion: str = ""
    """Actionable suggestion for how to fix the error."""


@dataclass
class ParseLocation:
    """Location of a parse error within the original document."""

    paragraph_index: int = 0
    """Index into the original paragraphs list (0-based)."""

    marker_type: str = ""
    """The marker type being parsed at the time of error:
    "PAGE", "COMPONENT", "ITEM", "QUESTION", "OPTION", "FEEDBACK",
    "LEARNING_OBJECTIVE", "KEY_TAKEAWAY", "CALLOUT", or "UNKNOWN"."""

    context_preview: str = ""
    """First 100 characters of the offending paragraph for display."""
```

---

## 7. Integration Architecture

### 7.1 Integration Points

The `MarkedDocumentParser` integrates into the existing pipeline at three points:

#### Point A — Ingestion Phase (ingestion_service.py:create_job)

```
Existing flow (ingestion_service.py lines 117-138):
    1. DocumentExtractor.extract_structured(tmp_path)
       → returns {"paragraphs": [...], "raw_text": "...", ...}
    2. DocumentSplitter.split_structured(paragraphs, filename)
       → returns [Section, Section, ...]
    3. Store extracted_sections, source_metadata on AIIngestionJobRecord

New flow (marker detection injected between 1 and 2):
    1. DocumentExtractor.extract_structured(tmp_path)
       → returns {"paragraphs": [...], ...}
    
    1a. IF AI_TEMPLATE_MARKING_ENABLED:
          parser = MarkedDocumentParser()
          IF parser.has_markers(paragraphs):
              marked_doc = parser.parse(paragraphs)
              errors = parser.validate(marked_doc)
              IF errors with severity == "error":
                  store errors in job, set status="marked_parse_error"
                  return early (breakdown will fail with errors)
              ELSE:
                  store MarkedDocument dict in job.source_metadata["marked_document"]
                  set source_metadata.marker_status = "detected"
                  skip DocumentSplitter (paragraphs preserved in source_metadata)
                  continue with sections from marker data
          ELSE:
              set source_metadata.marker_status = "absent"
              continue with existing pipeline (step 2)
    
    2. DocumentSplitter.split_structured(paragraphs, filename)  [only for unmarked]
    3. Store extracted_sections, source_metadata on AIIngestionJobRecord
```

**Code changes required:**
- `ingestion_service.py:create_job()` — Add marker detection after line 127 (after `paragraphs = structured.get("paragraphs", [])`)
- Import `MarkedDocumentParser` only when feature flag is enabled
- Store `MarkedDocument` as a dict (via `dataclasses.asdict()`) in `source_metadata["marked_document"]`

#### Point B — Breakdown Phase (ai_ingestion.py:_llm_propose_breakdown)

```
Existing flow (ai_ingestion.py lines 488-546):
    1. Call _heuristic_breakdown(sections, max_pages)
    2. If ambiguous pages → _llm_refine_ambiguous()
    3. If heuristic fails → _call_llm_for_breakdown()
    4. If LLM fails → _rule_based_breakdown()

New flow (marker-driven breakdown):
    1. IF job.source_metadata contains marker_status == "detected":
          marked_doc = MarkedDocument.from_dict(
              job.source_metadata["marked_document"]
          )
          IF marked_doc.has_markers:
              # Convert marked pages directly to page plan
              pages = _convert_marked_pages_to_plan(marked_doc)
              # Convert unmarked_paragraphs through heuristic/LLM
              IF marked_doc.unmarked_paragraphs:
                  unmarked_pages = _heuristic_breakdown(
                      marked_doc.unmarked_paragraphs
                  )
                  pages = _merge_marked_and_unmarked(pages, unmarked_pages)
              return pages
          # Marker status is "detected" but no pages — fallback to existing
          (continue with existing pipeline)
    
    2. Continue with existing _llm_propose_breakdown() for unmarked documents
```

**Code changes required:**
- `ai_ingestion.py:_llm_propose_breakdown()` — Add marker check at the beginning (before line 503)
- New helper function `_convert_marked_pages_to_plan(marked_doc)` — Converts `MarkedPage` objects to page plan dicts
- New helper function `_merge_marked_and_unmarked(marked_pages, unmarked_pages)` — Merges two page lists preserving order

#### Point C — Content Generation Phase (course_generator.py:_generate_page_content)

```
Existing flow (course_generator.py lines 749-787):
    1. Dispatch to template-specific generator
    2. Each generator returns ONE component

New flow (marker-driven generation):
    IF page has marked_components metadata:
        components = []
        FOR each MarkedComponent in page.metadata.marked_components:
            component = _generate_from_marked_component(marked_component)
            components.append(component)
        return components
    ELSE:
        # Continue with existing generator
        return dispatch_to_template_generator(...)
```

**Code changes required:**
- `course_generator.py:_generate_page_content()` — Add marker check before line 761
- New function `_generate_from_marked_component(marked_component)` — Creates component dict from marker data
- New function `_generate_nested_components(parent_component, children)` — Recursively generates nested components

### 7.2 Step-by-Step Flow for a Marked Document

```
Author creates DOCX with markers
    │
    ▼
POST /api/v1/ai/ingestions (upload)
    │
    ▼
ingestion_service.py:create_job()
    ├── DocumentExtractor.extract_structured() → paragraphs
    ├── IF AI_TEMPLATE_MARKING_ENABLED:
    │     ├── MarkedDocumentParser.has_markers(paragraphs) → True
    │     ├── MarkedDocumentParser.parse(paragraphs) → MarkedDocument
    │     ├── MarkedDocumentParser.validate(marked_doc)
    │     │     ├── IF errors → status="marked_parse_error", return errors
    │     │     └── IF clean → store in source_metadata
    │     └── Skip DocumentSplitter for marked content
    │
    ├── Store source_metadata.marker_status = "detected"
    ├── Store source_metadata.marked_document = asdict(marked_doc)
    └── Job status = "analyzed"
    │
    ▼
GET /api/v1/ai/ingestions/{job_id} (poll)
    ├── Response includes marker_status: "detected"
    └── Response includes parse_errors or null
    │
    ▼
POST /api/v1/ai/ingestions/{job_id}/propose-breakdown
    │
    ▼
ai_ingestion.py:_llm_propose_breakdown()
    ├── Check source_metadata.marker_status
    ├── IF "detected":
    │     ├── _convert_marked_pages_to_plan(marked_doc)
    │     │     ├── Each MarkedPage → page plan dict
    │     │     │     ├── title from marker
    │     │     │     ├── template_type from marker (no TemplateSelector)
    │     │     │     ├── order from marker
    │     │     │     ├── source_section_ids from paragraph indices
    │     │     │     └── marker_mode: true (new field)
    │     │     └── Include component hierarchy in page metadata
    │     ├── Handle unmarked paragraphs (existing pipeline)
    │     └── Return merged page plan
    │
    ├── Skip _heuristic_breakdown for marked pages
    ├── Skip _call_llm_for_breakdown for marked pages
    ├── Skip _rule_based_breakdown for marked pages
    └── Skip TemplateSelector for marked pages
    │
    ▼
POST /api/v1/ai/ingestions/{job_id}/review-plan
    │
    ▼ (author approves)
    │
    ▼
POST /api/v1/ai/generate-course
    │
    ▼
course_generator.py:_generate_page_content()
    ├── IF page has marked_components:
    │     ├── FOR each MarkedComponent:
    │     │     ├── _generate_from_marked_component()
    │     │     │     ├── component_type from marker
    │     │     │     ├── items from marker (with proper types)
    │     │     │     ├── content from marker raw_content
    │     │     │     └── nested components preserved
    │     │     └── Add to component list
    │     └── Return full component list (preserving order)
    │
    └── ELSE: existing template-specific generator
    │
    ▼
POST /api/v1/ai/generate-course/{job_id}/apply
    │
    ▼
Course created with correct pages, components, items
```

### 7.3 MarkedDocument Serialization

The `MarkedDocument` is stored as a dict in `AIIngestionJobRecord.source_metadata["marked_document"]` using `dataclasses.asdict()`.

Helper functions for serialization:

```python
def marked_document_to_dict(doc: MarkedDocument) -> dict:
    """Convert MarkedDocument to a dict for JSON storage.
    Handles nested dataclasses recursively."""
    return asdict(doc)

def marked_document_from_dict(data: dict) -> MarkedDocument:
    """Reconstruct MarkedDocument from a dict (JSON-loaded).
    Handles nested dataclasses recursively."""
    # Rebuild MarkedDocument, MarkedPage, MarkedComponent, MarkedItem,
    # ParseError, ParseLocation from flat dicts
    ...
```

---

## 8. State Machine Specification

### 8.1 New States for Marked Documents

The existing job status values (`uploaded`, `analyzed`, `page_plan_ready`, `plan_approved`, `generated`, `completed`, `failed`) gain two new states:

| State | Description | Terminal? |
|-------|-------------|-----------|
| `marked_detected` | Markers detected in the uploaded file | No |
| `marked_parsed` | Markers successfully parsed, MarkedDocument built | No |
| `marked_parse_error` | Markers found but parsing failed | Yes (transient — re-upload allowed) |

### 8.2 State Transition Diagram

```
uploaded ──→ extracting ──→ marked_detected ──→ marked_parsed ──→ page_plan_ready
    │              │               │                   │
    │              │               │            (on error)
    │              │               │                   │
    │              │               │           marked_parse_error
    │              │               │                   │
    │              │               │          (user re-uploads)
    │              │               │                   │
    │              │               │             uploaded
    │              │               │
    │              │         (no markers)
    │              │               │
    │              ▼               ▼
    │          analyzed ──→ page_plan_ready
    │
    └──── (same as existing)
```

### 8.3 State Definitions

#### `marked_detected`

| Property | Value |
|----------|-------|
| Entry condition | `MarkedDocumentParser.has_markers()` returns True |
| Data required | `source_metadata.marker_status = "detected"` |
| Transition to | `marked_parsed` (on successful `parse()`) |
| Transition to | `marked_parse_error` (on parse failure with errors) |
| Transition to | `analyzed` (if `AI_TEMPLATE_MARKING_ENABLED=false` — skip marker path) |
| API response field | `marker_status: "detected"` |

#### `marked_parsed`

| Property | Value |
|----------|-------|
| Entry condition | `MarkedDocumentParser.parse()` succeeds, `validate()` returns no errors |
| Data required | `source_metadata.marked_document` = fully populated MarkedDocument dict |
| Transition to | `page_plan_ready` (on breakdown, converting marked pages to plan) |
| Transition to | `analyzed` (on breakdown, using existing pipeline for unmarked sections) |
| API response field | `marker_status: "parsed"`, `marker_page_count: N` |

#### `marked_parse_error`

| Property | Value |
|----------|-------|
| Entry condition | `MarkedDocumentParser.parse()` or `validate()` returns errors |
| Data required | `source_metadata.marker_errors` = list of structured errors |
| Allowed action | Re-upload the document with fixes |
| Transition to | `uploaded` (on re-upload) |
| API response field | `marker_status: "parse_error"`, `marker_errors: [...]` |

### 8.4 API Responses by State

**`marked_parsed` state — GET /api/v1/ai/ingestions/{job_id}:**
```json
{
    "status": "ok",
    "job_id": "abc-123",
    "job_status": "analyzed",
    "marker_status": "parsed",
    "marker_page_count": 12,
    "marker_component_count": 28,
    "marker_item_count": 84,
    "source_metadata": {
        "marker_status": "parsed",
        "marker_document_summary": {
            "has_markers": true,
            "page_count": 12,
            "component_count": 28,
            "item_count": 84
        }
    }
}
```

**`marked_parse_error` state — GET /api/v1/ai/ingestions/{job_id}:**
```json
{
    "status": "ok",
    "job_id": "abc-123",
    "job_status": "analyzed",
    "marker_status": "parse_error",
    "marker_errors": [
        {
            "code": "UNCLOSED_MARKER",
            "message": "Page marker starting at paragraph 12 is not closed. Expected [/PAGE] before end of document.",
            "location": {
                "paragraph_index": 12,
                "marker_type": "PAGE",
                "context_preview": "[PAGE: content-text | title: Phishing Overview]"
            },
            "severity": "error",
            "suggestion": "Add a [/PAGE] closing marker at the end of this page's content."
        }
    ],
    "warnings": ["2 pages extracted, 1 has errors. Fix errors and re-upload."]
}
```

---

## 9. Validation Rules

### 9.1 Structural Rules

| Rule ID | Rule | Severity | Error Code |
|---------|------|----------|------------|
| S-01 | Pages must not overlap. A paragraph inside `[PAGE]...[/PAGE]` cannot also be inside another `[PAGE]` block. | error | `OVERLAPPING_PAGES` |
| S-02 | Every `[PAGE:]` must be matched by a `[/PAGE]`. | error | `UNCLOSED_MARKER` |
| S-03 | Every `[COMPONENT:]` must be matched by a `[/COMPONENT]`. | error | `UNCLOSED_MARKER` |
| S-04 | Every `[ITEM:]` must be matched by a `[/ITEM]`. | error | `UNCLOSED_MARKER` |
| S-05 | Every `[QUESTION:]` must be matched by a `[/QUESTION]`. | error | `UNCLOSED_MARKER` |
| S-06 | Every `[OPTION:]` must be matched by a `[/OPTION]`. | error | `UNCLOSED_MARKER` |
| S-07 | Markers must be properly nested: `[PAGE] > [COMPONENT] > [ITEM]`. Cross-nesting is invalid (e.g., `[PAGE][ITEM][/PAGE][/ITEM]`). | error | `NESTING_VIOLATION` |
| S-08 | `[COMPONENT]` markers must appear inside a `[PAGE]` block. | error | `NESTING_VIOLATION` |
| S-09 | `[ITEM]` markers must appear inside a `[COMPONENT]` block. | error | `NESTING_VIOLATION` |
| S-10 | `[QUESTION]` markers must appear inside a `[COMPONENT: final-assessment]` block. | error | `NESTING_VIOLATION` |
| S-11 | `[OPTION]` markers must appear inside a `[QUESTION]` block. | error | `NESTING_VIOLATION` |
| S-12 | `[LEARNING_OBJECTIVE]` must appear directly inside `[PAGE]`, not inside `[COMPONENT]`. | warning | `NESTING_VIOLATION` |
| S-13 | `[KEY_TAKEAWAY]` must appear directly inside `[PAGE]`, not inside `[COMPONENT]`. | warning | `NESTING_VIOLATION` |
| S-14 | Nesting depth must not exceed `max_nesting` (default 2). | error | `MAX_NESTING_EXCEEDED` |
| S-15 | `[/PAGE]` with no matching `[PAGE:]` is invalid. | warning | `UNKNOWN_MARKER` |
| S-16 | `[/COMPONENT]` with no matching `[COMPONENT:]` is invalid. | warning | `UNKNOWN_MARKER` |

### 9.2 Type Rules

| Rule ID | Rule | Severity | Error Code |
|---------|------|----------|------------|
| T-01 | `template_type` in `[PAGE:]` must be one of: content-text, tabs, accordion, click-reveal, final-assessment, welcome, summary. | error | `INVALID_TEMPLATE_TYPE` |
| T-02 | `component_type` in `[COMPONENT:]` must be one of the canonical types (or from component_registry if provided). | error | `INVALID_COMPONENT_TYPE` |
| T-03 | `question_type` in `[QUESTION:]` must be one of: mcq, true-false, multi-select. | error | `INVALID_QUESTION_TYPE` |
| T-04 | `callout_type` in `[CALLOUT:]` must be one of: tip, warning, note, important. | warning | `INVALID_ATTRIBUTE_VALUE` |

### 9.3 Content Rules

| Rule ID | Rule | Severity | Error Code |
|---------|------|----------|------------|
| C-01 | `final-assessment` component must contain at least 3 `[QUESTION]` blocks. | error | `TOO_FEW_QUESTIONS` |
| C-02 | `final-assessment` component must not exceed 50 `[QUESTION]` blocks. | error | `TOO_MANY_ITEMS` |
| C-03 | `tabs` component must contain 2-6 `[ITEM]` blocks. | warning | `TOO_FEW_ITEMS` / `TOO_MANY_ITEMS` |
| C-04 | `accordion` component must contain 2-20 `[ITEM]` blocks. | warning | `TOO_FEW_ITEMS` / `TOO_MANY_ITEMS` |
| C-05 | `click-reveal` component must contain 2-10 `[ITEM]` blocks. | warning | `TOO_FEW_ITEMS` / `TOO_MANY_ITEMS` |
| C-06 | `mcq` question must have exactly 1 option with `correct: true`. | error | `MISSING_CORRECT_ANSWER` |
| C-07 | `true-false` question must have exactly 1 option with `correct: true`. | error | `MISSING_CORRECT_ANSWER` |
| C-08 | `multi-select` question must have at least 1 option with `correct: true`. | error | `MISSING_CORRECT_ANSWER` |
| C-09 | Every `QUESTION` must contain at least 2 `[OPTION]` blocks. | error | `TOO_FEW_OPTIONS` |
| C-10 | A component with no content and no items is empty. | warning | `EMPTY_COMPONENT` |
| C-11 | `[COMPONENT: content-text]` with no raw content is empty. | warning | `EMPTY_COMPONENT` |
| C-12 | Passing score in `[COMPONENT: final-assessment \| passing_score: N]` must be 0-100. | warning | `INVALID_ATTRIBUTE_VALUE` |

### 9.4 Cross-Reference Rules

| Rule ID | Rule | Severity | Error Code |
|---------|------|----------|------------|
| X-01 | No two pages may have the same `title` attribute (case-insensitive). | warning | `DUPLICATE_PAGE_TITLE` |
| X-02 | No two pages may have the same `order` attribute. | warning | `DUPLICATE_ORDER_INDEX` |
| X-03 | All `order` attributes within a page must be unique across components. | warning | `DUPLICATE_ORDER_INDEX` |
| X-04 | All `order` attributes within a component must be unique across items. | warning | `DUPLICATE_ORDER_INDEX` |
| X-05 | At least one page must exist if `has_markers` is True and any `[PAGE]` marker is present. | error | `NO_PAGES` |

---

## 10. Error Handling Specification

### 10.1 Error Code Reference

| Code | Message Template | Severity | Suggestion | Example |
|------|------------------|----------|------------|---------|
| `UNCLOSED_MARKER` | "`{MARKER_TYPE}` marker starting at paragraph {N} is not closed. Expected `{/MARKER_TYPE}` before end of document." | error | "Add a `[/{MARKER_TYPE}]` closing marker at the end of this block." | `[PAGE: content-text` at paragraph 12 with no `[/PAGE]` |
| `INVALID_TEMPLATE_TYPE` | "Invalid template type '{TYPE}' in `[PAGE:]` at paragraph {N}. Allowed: welcome, summary, content-text, tabs, accordion, click-reveal, final-assessment." | error | "Replace '{TYPE}' with one of the allowed template types." | `[PAGE: video-page]` — "video-page" is not allowed |
| `INVALID_COMPONENT_TYPE` | "Invalid component type '{TYPE}' in `[COMPONENT:]` at paragraph {N}. Allowed: content-text, tabs, accordion, click-reveal, final-assessment." | error | "Replace '{TYPE}' with a valid component type." | `[COMPONENT: carousel]` |
| `OVERLAPPING_PAGES` | "Paragraph {N} is inside two `[PAGE]` blocks. Each paragraph can belong to only one page." | error | "Ensure `[/PAGE]` is placed before the next `[PAGE:]`. Pages cannot overlap." | `[PAGE: tabs]...[PAGE: accordion]...[/PAGE]...[/PAGE]` |
| `NESTING_VIOLATION` | "`{MARKER_TYPE}` at paragraph {N} is not allowed inside `{PARENT_TYPE}`. Expected context: `{EXPECTED_CONTEXT}`." | error | "Move the `[{MARKER_TYPE}]` marker to the correct location." | `[ITEM]` directly inside `[PAGE]` |
| `MISSING_REQUIRED_ATTRIBUTE` | "`[PAGE:]` at paragraph {N} is missing required attribute '{ATTR}'." | error | "Add `{ATTR}: <value>` to the marker." | `[PAGE:]` without template_type |
| `DUPLICATE_PAGE_TITLE` | "Page title '{TITLE}' is used by both page {N} and page {M}. Page titles should be unique." | warning | "Rename one of the pages to have a unique title." | Two `[PAGE: content-text \| title: Overview]` |
| `EMPTY_COMPONENT` | "`[COMPONENT: {TYPE}]` at paragraph {N} has no content and no items." | warning | "Add text content between the markers, or remove the empty component." | `[COMPONENT: content-text][/COMPONENT]` |
| `UNKNOWN_MARKER` | "Unknown marker syntax at paragraph {N}: '{PREVIEW}'. This text will be treated as literal content." | warning | "Check for typos in the marker syntax. Use `[//]: #` for comments." | `[PAGEE: content-text]` (typo) |
| `MAX_NESTING_EXCEEDED` | "Nesting depth exceeds maximum of {MAX} at paragraph {N}. Current depth: {DEPTH}." | error | "Reduce nesting by restructuring the components. The maximum depth is {MAX}." | `[PAGE] > [COMPONENT: tabs] > [ITEM] > [COMPONENT: accordion] > [ITEM] > [COMPONENT: content-text]` |
| `INVALID_ATTRIBUTE_VALUE` | "Invalid value '{VALUE}' for attribute '{ATTR}' at paragraph {N}. Expected one of: {EXPECTED}." | warning | "Replace '{VALUE}' with one of the allowed values." | `[CALLOUT: error]` — "error" is not a valid callout type |
| `MISSING_CORRECT_ANSWER` | "`[QUESTION:]` at paragraph {N} (type: {TYPE}) has no option marked `correct: true`. Exactly 1 option must be correct for {TYPE}." | error | "Add `correct: true` to exactly one `[OPTION:]` marker." | MCQ with no correct answer designated |
| `TOO_FEW_QUESTIONS` | "`[COMPONENT: final-assessment]` at paragraph {N} has only {COUNT} questions. Minimum is 3." | error | "Add more `[QUESTION:]` markers to reach at least 3 questions." | Assessment with only 1 question |
| `TOO_MANY_ITEMS` | "`[COMPONENT: {TYPE}]` at paragraph {N} has {COUNT} items. Maximum is {MAX}." | error | "Reduce the number of `[ITEM:]` markers to {MAX} or fewer." | Tabs with 10 items (max is 6) |
| `TOO_FEW_ITEMS` | "`[COMPONENT: {TYPE}]` at paragraph {N} has only {COUNT} items. Minimum is {MIN}." | warning | "Add more `[ITEM:]` markers to reach at least {MIN} items." | Accordion with 1 item (min is 2) |
| `TOO_FEW_OPTIONS` | "`[QUESTION:]` at paragraph {N} has only {COUNT} options. Minimum is 2." | error | "Add more `[OPTION:]` markers to reach at least 2 options." | MCQ with only 1 option |
| `NO_PAGES` | "The document has markers but no `[PAGE:]` blocks were found." | error | "Add at least one `[PAGE: template_type]...[/PAGE]` block to define page structure." | Document with `[COMPONENT:]` but no `[PAGE:]` |
| `DUPLICATE_ORDER_INDEX` | "Order index {ORDER} is used by both {ITEM_TYPE} at paragraphs {N} and {M}." | warning | "Assign unique `order` values to each item." | Two pages with `order: 2` |
| `INVALID_QUESTION_TYPE` | "Invalid question type '{TYPE}' in `[QUESTION:]` at paragraph {N}. Allowed: mcq, true-false, multi-select." | error | "Replace '{TYPE}' with one of: mcq, true-false, multi-select." | `[QUESTION: essay]` |

### 10.2 Error Collection Strategy

- All errors are collected in a single pass of `parse()` and `validate()` — no fail-fast within a document
- If `parse()` encounters a fatal error (unclosed marker at EOF), it stops and returns partial results with the error
- `validate()` always returns all validation errors in a single pass
- Errors are sorted by paragraph_index before return
- An empty error list means the document is valid for marker-based processing

---

## 11. API Changes

### 11.1 POST /api/v1/ai/ingestions (upload_document)

**File:** `app/routers/ai_ingestion.py` lines 20-63

**Change:** Response gains `marker_status` field when `AI_TEMPLATE_MARKING_ENABLED` is true.

**Response (unchanged fields omitted for brevity):**
```json
{
    "status": "ok",
    "job_id": "abc-123",
    "job_status": "analyzed",
    "marker_status": "detected",         // NEW: "detected" | "parsed" | "parse_error" | "absent" | null
    "marker_page_count": 12,             // NEW: when marker_status is "parsed"
    "marker_errors": null,               // NEW: array of ParseError dicts when status is "parse_error"
    "progress": 1.0,
    "warnings": [],
    "source_metadata": {
        "marker_status": "detected",     // NEW
        "marker_document_summary": {     // NEW: summary of parsed markers
            "has_markers": true,
            "page_count": 12,
            "component_count": 28,
            "item_count": 84
        }
    }
}
```

**Backward compatibility:** When `AI_TEMPLATE_MARKING_ENABLED` is false, `marker_status` is absent from the response. All existing fields remain unchanged.

### 11.2 GET /api/v1/ai/ingestions/{job_id} (get_ingestion_job)

**File:** `app/routers/ai_ingestion.py` lines 66-92

**Change:** Response gains marker-related fields when applicable.

**Response additions:**
```json
{
    "status": "ok",
    "job_id": "abc-123",
    "job_status": "analyzed",
    "marker_status": "parsed",       // NEW
    "marker_page_count": 12,         // NEW
    "marker_component_count": 28,    // NEW
    "marker_item_count": 84,         // NEW
    "marker_errors": null            // NEW: null when clean, array when parse_error
}
```

**Backward compatibility:** Fields are absent when no markers are present or the feature flag is off.

### 11.3 POST /api/v1/ai/ingestions/{job_id}/propose-breakdown

**File:** `app/routers/ai_ingestion.py` lines 135-243

**Change:** Response gains `marker_mode` field.

**Response additions:**
```json
{
    "status": "ok",
    "job_id": "abc-123",
    "plan": [ ... ],
    "total_proposed": 12,
    "source_sections": 12,
    "marker_mode": true,             // NEW: true when breakdown came from markers
    "marker_page_count": 10,         // NEW: number of pages from markers
    "unmarked_page_count": 2,        // NEW: number of pages from heuristic/LLM (mixed documents)
    "validation": {
        "valid": true,
        "coverage": 1.0,
        "errors": [],
        "warnings": []
    }
}
```

**Impact on plan items:** Each page in the `plan` array that originated from markers includes:
```json
{
    "proposed_title": "Phishing Attack Vectors",
    "suggested_template_type": "tabs",
    "rationale": "From markers — template type explicitly specified by author [MARKER MODE]",
    "source_section_ids": [10, 11, 12, 13, 14, 15],
    "order": 0,
    "marker_mode": true,
    "marked_components": [
        {
            "component_type": "content-text",
            "order_index": 0,
            "raw_content": "Phishing is a form of social engineering...",
            "items": [],
            "children": []
        },
        {
            "component_type": "accordion",
            "order_index": 1,
            "raw_content": "",
            "items": [
                {"title": "Spear Phishing", "content": "Targeted attacks...", "item_type": "accordion-item"},
                {"title": "Whaling", "content": "Attacks targeting...", "item_type": "accordion-item"}
            ],
            "children": []
        }
    ]
}
```

### 11.4 Error Response for marked_parse_error

When a document has marker errors, the `propose-breakdown` endpoint returns an error:

```json
{
    "status": "error",
    "code": "MARKER_PARSE_ERROR",
    "message": "The uploaded document contains marker errors. Fix the errors and re-upload.",
    "marker_errors": [
        {
            "code": "INVALID_TEMPLATE_TYPE",
            "message": "Invalid template type 'video-page' in [PAGE:] at paragraph 5...",
            "location": {
                "paragraph_index": 5,
                "marker_type": "PAGE",
                "context_preview": "[PAGE: video-page | title: Phishing Overview]"
            },
            "severity": "error",
            "suggestion": "Replace 'video-page' with one of: content-text, tabs, accordion, click-reveal, final-assessment, welcome, summary."
        }
    ]
}
```

---

## 12. Acceptance Criteria

### FR-1: Marker Detection

**Happy Path:**
- Given: A DOCX containing `[PAGE: content-text]...[/PAGE]` in paragraph 5
- When: `has_markers(paragraphs)` is called
- Then: Returns `True`

- Given: A DOCX with no `[` character in any paragraph
- When: `has_markers(paragraphs)` is called
- Then: Returns `False`

**Error Path:**
- Given: A DOCX with escaped marker `\[PAGE: content-text\]`
- When: `has_markers(paragraphs)` is called
- Then: Returns `False` (escaped markers are not detected)

**Performance:**
- Given: 2000 paragraphs with markers
- When: `has_markers()` executes
- Then: Completes within 50ms

### FR-2: Page Boundary Markers

**Happy Path:**
- Given: `[PAGE: content-text]First paragraph[/PAGE]`
- When: `parse()` executes
- Then: 1 `MarkedPage` with `source_paragraph_indices=[0, 1]` (opening + content + closing)

- Given: 3 consecutive `[PAGE]...[/PAGE]` blocks
- When: `parse()` executes
- Then: 3 pages with indices 0, 1, 2

**Error Path:**
- Given: `[PAGE: content-text]...` with no `[/PAGE]` before EOF
- When: `parse()` executes
- Then: `ParseError` with code `UNCLOSED_MARKER`, paragraph_index points to opening `[PAGE:]`

### FR-3: Template Type Specification

**Happy Path:**
- Given: `[PAGE: accordion]`
- When: page is parsed
- Then: `page.template_type = "accordion"`

**Error Path:**
- Given: `[PAGE: video-page]`
- When: `validate()` executes
- Then: `ParseError` with code `INVALID_TEMPLATE_TYPE`

**Integration:**
- Given: A page plan built from markers
- When: The breakdown endpoint returns the plan
- Then: `plan[0].suggested_template_type` equals the marker's template_type; `marker_mode: true`

### FR-4: Component Specification

**Happy Path:**
- Given: `[COMPONENT: content-text]Hello[/COMPONENT]`
- When: `parse()` executes
- Then: 1 `MarkedComponent` with `component_type="content-text"`, `raw_content="Hello"`

- Given: 3 components in one page
- When: `parse()` executes
- Then: 3 components with order_index 0, 1, 2

**Error Path:**
- Given: `[COMPONENT: unknown-type]`
- When: `validate()` executes and component_registry is provided
- Then: `ParseError` with code `INVALID_COMPONENT_TYPE`

### FR-5: Component Item Specification

**Happy Path:**
- Given: `[COMPONENT: accordion][ITEM: Title]Content[/ITEM][ITEM: Title 2]Content 2[/ITEM][/COMPONENT]`
- When: `parse()` executes
- Then: 2 items with correct title, content, and `item_type="accordion-item"`

**Error Path:**
- Given: `[COMPONENT: tabs]` with 1 `[ITEM]`
- When: `validate()` executes
- Then: `ParseError` with code `TOO_FEW_ITEMS` (warning)

### FR-6: Assessment Question Markers

**Happy Path:**
- Given: A complete `[QUESTION: mcq]` with options and feedback
- When: `parse()` executes
- Then: Question with 4 options, `correct_answer` resolved, `feedback` populated

**Error Path:**
- Given: `[QUESTION: mcq]` with no correct answer
- When: `validate()` executes
- Then: `ParseError` with code `MISSING_CORRECT_ANSWER`

### FR-7: Nested Component Support

**Happy Path:**
- Given: `[COMPONENT: tabs][ITEM: Tab1][COMPONENT: content-text]Content[/COMPONENT][/ITEM][/COMPONENT]`
- When: `parse()` executes
- Then: `component.children[0]` exists with `component_type="content-text"`

**Error Path:**
- Given: 3 levels of nesting with `max_nesting=2`
- When: `parse()` executes
- Then: `ParseError` with code `MAX_NESTING_EXCEEDED`

### FR-8: Mixed Marked/Unmarked Documents

**Happy Path:**
- Given: A DOCX with 2 marked pages and 1 unmarked section
- When: `parse()` executes
- Then: `MarkedDocument.pages` = 2, `MarkedDocument.unmarked_paragraphs` = 1 section's paragraphs

**Integration:**
- Given: Mixed document in the breakdown phase
- When: `_llm_propose_breakdown()` runs
- Then: Returns 3 pages total (2 from markers, 1 from heuristic/LLM), `marker_mode: true`, `unmarked_page_count: 1`

### FR-9: Parse Error Reporting

**Happy Path:**
- Given: A DOCX with 3 parse errors
- When: `parse()` executes
- Then: 3 `ParseError` objects returned in a single pass

**Integration:**
- Given: A document with parse errors uploaded
- When: `GET /api/v1/ai/ingestions/{job_id}` is polled
- Then: `marker_status: "parse_error"`, `marker_errors` array populated

### FR-10: Backward Compatibility

**Given:** The full test suite
**When:** All 20 test runners execute
**Then:** 834 tests pass with 0 failures

**Given:** A document without markers
**When:** The upload-extract-breakdown-generate-apply pipeline runs
**Then:** All existing behavior preserved, no new fields in responses (or fields are `null`/absent)

**Given:** `AI_TEMPLATE_MARKING_ENABLED=false`
**When:** A marked DOCX is uploaded
**Then:** Markers are ignored; `source_metadata.marker_status` is absent; existing pipeline handles it

---

## 13. Backward Compatibility Requirements

### 13.1 Test Suite Compatibility

| Requirement | Verification |
|-------------|-------------|
| All 834 existing tests pass | Run all 20 standalone test runners in `tests/run_*.py` before commit |
| No regressions in existing pipeline behavior | Run `tests/run_e2e_regression_tests.py` (28 tests) |
| Postman Flow 10/11 works for unmarked documents | Execute Postman collection Flow 10/11 for unmarked DOCX |
| All 44 AI endpoints unchanged | Verify OpenAPI schema diff shows only additive changes |

### 13.2 API Contract Compatibility

| Requirement | Implementation |
|-------------|----------------|
| Zero breaking changes to existing API contracts | All new fields are additive; existing parsers ignore unknown fields |
| No new required request parameters | All marker-related inputs are implicit (document content) |
| No new required response fields | `marker_status` and `marker_errors` are only present when relevant |
| Existing responses unchanged for unmarked documents | Response shape is identical to pre-marker code for unmarked documents |

### 13.3 Feature Flag Gating

```python
# Environment variable
AI_TEMPLATE_MARKING_ENABLED = os.getenv("AI_TEMPLATE_MARKING_ENABLED", "false").lower() == "true"
```

| Flag Value | Behavior |
|------------|----------|
| `false` (default) | `MarkedDocumentParser` is never instantiated. No marker detection. Existing pipeline unchanged. |
| `true` | Marker detection runs. Marked documents route to marker pipeline. Unmarked documents unchanged. |

### 13.4 Data Model Compatibility

| Requirement | Implementation |
|-------------|----------------|
| No new DB tables for MVP | `MarkedDocument` stored in existing `source_metadata` JSON column |
| No schema migrations required | All state stored in `AIIngestionJobRecord.source_metadata` dict |
| No new ORM models | `MarkedDocumentParser` is stateless — no persistence |

---

## 14. Open Questions & Risks

### 14.1 Open Questions

**Q1: What if markers contradict each other?**
Example: `[PAGE: tabs \| order: 1]...[PAGE: accordion \| order: 1]` — two pages claiming order 1.
Resolution: The validation engine detects duplicate order indices and emits a warning (`DUPLICATE_ORDER_INDEX`). Processing continues with sequential ordering auto-assigned. Authors should fix the conflict but it does not block processing.

**Q2: What if markers reference non-existent sections?**
Markers ARE the section boundaries — there is no cross-reference to external section IDs. However, if a `[PAGE]` marker has a `source_excerpt` or references content that doesn't exist, the parser simply captures whatever text falls between the opening and closing markers. Empty content generates an `EMPTY_COMPONENT` warning but does not block processing.

**Q3: What if the DOCX has mixed marked/unmarked content?**
Handled by FR-8 and the `MarkedDocument.unmarked_paragraphs` list. Paragraphs outside all `[PAGE]...[/PAGE]` boundaries are collected and passed to the existing heuristic/LLM pipeline. The breakdown phase merges marker pages and pipeline-generated pages into a single ordered plan.

**Q4: How to handle marker syntax in different languages?**
MVP is English-only. All marker keywords (`PAGE`, `COMPONENT`, `ITEM`, `QUESTION`, etc.) are English and case-sensitive. Non-English keyword variants are a post-MVP expansion. However, the content INSIDE markers can be any language — the markers themselves define structure, not content.

**Q5: How do markers interact with table content?**
DOCX tables are extracted by `DocumentExtractor.extract_structured()` into `table_text`. Markers inside table cells are detected but the parser treats each cell's text independently. For MVP, authors should place markers in non-table paragraphs. Table-marker integration is a post-MVP enhancement.

**Q6: Do markers survive DOCX editing and format conversion?**
Markers are plain text inside paragraph content. They survive DOCX editing in Word, Google Docs, and LibreOffice as long as the tools don't strip text or auto-format brackets. They WILL survive Save As → .docx. They may NOT survive Save As → .pdf (text extraction fidelity varies). Risk: Word auto-correct might convert `[` to `([` in some locales — authors should disable auto-correct for marker content.

### 14.2 Risks & Mitigations

**R1: Authors might find marker syntax cumbersome.**
- **Impact:** Low adoption, authors continue using the heuristic pipeline
- **Likelihood:** Medium
- **Mitigation:** Provide a `marker-template.docx` (a boilerplate DOCX with common marker structures) that authors can download and fill in. The syntax is intentionally minimal (5 marker types, 5 attributes). For power users, the deterministic output eliminates 3-5 LLM iteration cycles.

**R2: Markers might get corrupted during DOCX editing.**
- **Impact:** Parse errors, author frustration
- **Likelihood:** Medium
- **Mitigation:** The parser is liberal in what it accepts (warnings > errors for most violations). The `marked_parse_error` state provides specific error messages with paragraph references. Authors fix errors and re-upload — the idempotency service prevents duplicate processing.

**R3: Feature flag off by default may limit testing.**
- **Impact:** Bugs discovered late if flag is left off during development
- **Likelihood:** High (default is `false`)
- **Mitigation:** Enable on test/staging environments. Include `AI_TEMPLATE_MARKING_ENABLED=true` in the Postman environment for Flow 10/11 tests.

**R4: Nested component content generation may exceed LLM context windows.**
- **Impact:** Truncated or failed content generation for complex nested structures
- **Likelihood:** Low (nested structures are generally small)
- **Mitigation:** The LLM content generation for marked components only needs to generate CONTENT TEXT, not structure. The structure comes from the markers. Each component's raw_content is typically under 500 chars.

**R5: Mixed marked/unmarked documents may produce confusing page plans.**
- **Impact:** Page plan shows "from markers" and "from heuristic" labels that confuse authors
- **Likelihood:** Medium
- **Mitigation:** The breakdown response includes `marker_mode: true` and per-page `marker_mode` flags. The frontend can display marker-sourced pages with an icon/tooltip. Authors can always switch a marker-sourced page back to the heuristic pipeline by removing markers and re-uploading.

**R6: Marker syntax overlaps with markdown or other bracket conventions.**
- **Impact:** False positive marker detection in documents that use brackets for other purposes
- **Likelihood:** Low
- **Mitigation:** Minimal syntax: only `[PAGE:`, `[COMPONENT:`, `[ITEM:`, `[QUESTION:`, `[OPTION:`, `[FEEDBACK]`, `[LEARNING_OBJECTIVE]`, `[KEY_TAKEAWAY]`, `[CALLOUT:]`, `[//]` are recognized as markers. All other bracket content (`[reference]`, `[note]`, `[source]`) is treated as literal text. The case-sensitive, specific keyword prevents false positives.

**R7: Escaping overhead for documents that need literal `[PAGE:` text.**
- **Impact:** Authors must escape legitimate bracket text
- **Likelihood:** Low
- **Mitigation:** Documents that don't use markers don't trigger the marker pipeline at all (`has_markers()` returns False). The escape character `\` is standard across many markup languages. Author documentation includes explicit examples.

---

## Appendix A: Implementation File List

| File | Change Type | Description |
|------|-------------|-------------|
| `app/services/ai/marked_document_parser.py` | NEW | `MarkedDocumentParser` class (+ helpers) |
| `app/services/ai/marked_document_models.py` | NEW | `MarkedDocument`, `MarkedPage`, `MarkedComponent`, `MarkedItem`, `ParseError`, `ParseLocation` dataclasses |
| `app/services/ai/__init__.py` | MODIFY | Export new classes |
| `app/services/ai/ingestion_service.py` | MODIFY | Add marker detection after DOCX extraction (after line 127) |
| `app/routers/ai_ingestion.py` | MODIFY | Add `marker_mode` flag and `_convert_marked_pages_to_plan()` helper |
| `app/services/ai/course_generator.py` | MODIFY | Add `_generate_from_marked_component()` for marker-driven content generation |
| `app/services/ai/marker_component_generator.py` | NEW | Template-specific content generation from marked components |
| `app/services/ai/template_contracts.py` | MODIFY | Add `welcome`, `summary` to business rules (if not already present) |
| `app/services/ai/config.py` | MODIFY | Add `AI_TEMPLATE_MARKING_ENABLED` config |
| `tests/run_marker_parser_tests.py` | NEW | 50+ tests for `MarkedDocumentParser` |
| `tests/run_marker_integration_tests.py` | NEW | 20+ integration tests for marker pipeline |
| `docs/FRD_Template_Marking_System.md` | NEW | This document |

## Appendix B: Test File Structure

```
tests/
├── run_marker_parser_tests.py          # 50+ tests (marker parsing)
│   ├── test_has_markers_true           # FR-1 markers detected
│   ├── test_has_markers_false          # FR-1 no markers
│   ├── test_has_markers_escaped        # FR-1 escaped markers
│   ├── test_parse_single_page          # FR-2 single page
│   ├── test_parse_multiple_pages       # FR-2 multiple pages
│   ├── test_parse_page_attributes      # FR-3 template type
│   ├── test_parse_invalid_template     # FR-3 invalid type
│   ├── test_parse_single_component     # FR-4 single component
│   ├── test_parse_three_components     # FR-4 multiple components
│   ├── test_parse_accordion_items      # FR-5 accordion items
│   ├── test_parse_tab_items            # FR-5 tab items
│   ├── test_parse_mcq_question         # FR-6 MCQ question
│   ├── test_parse_true_false           # FR-6 true-false
│   ├── test_parse_nested_components    # FR-7 nested components
│   ├── test_parse_mixed_marked         # FR-8 mixed document
│   ├── test_parse_error_reporting      # FR-9 error reporting
│   ├── test_validate_missing_correct_answer  # Content rule C-06
│   ├── test_validate_too_few_questions        # Content rule C-01
│   ├── test_validate_too_few_items            # Content rule C-03
│   ├── test_validate_max_nesting              # Structural rule S-14
│   ├── test_validate_overlapping_pages        # Structural rule S-01
│   ├── test_validate_duplicate_page_title     # Cross-reference rule X-01
│   ├── ... (50+ total)
│
├── run_marker_integration_tests.py     # 20+ tests (marker pipeline)
│   ├── test_upload_marked_docx         # Upload with markers → marker_status="detected"
│   ├── test_upload_unmarked_docx       # Upload without markers → marker_status="absent"
│   ├── test_breakdown_marked_docx      # Breakdown from markers → marker_mode=true
│   ├── test_breakdown_unmarked_docx    # Breakdown without markers → marker_mode=false
│   ├── test_mixed_document_breakdown   # Mixed → marker_mode=true, unmarked_page_count=N
│   ├── test_parse_error_state          # Marked document with errors → marked_parse_error
│   ├── test_re_upload_after_error      # Fix errors and re-upload
│   ├── test_generate_from_markers      # Content generation preserves components
│   ├── test_generate_nested_components # Nested components generated correctly
│   ├── test_feature_flag_disabled      # AI_TEMPLATE_MARKING_ENABLED=false → markers ignored
│   ├── ... (20+ total)
```

---

*End of FRD-TMS-001 — Template Marking System Functional Requirements*
