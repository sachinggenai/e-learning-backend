# Template Marking System — Intent of Work & AI Prompts for FRD/TRD

> **Date:** 2026-07-11
> **Branch:** `agentic-ai-architecture`
> **Trigger:** DOCX course creation failure from `SB2-Cybersecurity Awareness for the Modern Workplace.docx`
> **Out of Scope:** Code changes. This document defines intent and provides AI-ready prompts only.

---

## Part A: Intent of Work

### A.1 Problem Statement

When a user uploads an unstructured DOCX (e.g., cybersecurity awareness training) through the AI course creation pipeline (Flow 10/11 — Upload → Extract → Breakdown → Generate → Apply), the LLM-driven page breakdown and template selection fail in three critical ways:

| Failure Mode | Root Cause | Impact |
|---|---|---|
| **Page splitting is wrong** | `DocumentSplitter` splits by Word heading styles or regex — no semantic understanding of which sections should form a single page vs. multiple pages | Pages are over-split (one heading = one page) or under-split (large sections merged incorrectly) |
| **Component hierarchy is lost** | The pipeline has no concept of Page → Component → Nested Component. Each page gets exactly one top-level component. | Complex pages that need multiple components (e.g., content-text + callout + key-takeaways, or tabs containing accordion items) collapse to a single flat component |
| **Template selection is inaccurate** | `TemplateSelector` uses keyword/regex heuristics (e.g., "quiz" → `final-assessment`) and `_heuristic_breakdown` uses regex on heading text (`PAGE X —`, `Tab N —`, `Question N`) — both fail when the document doesn't follow the expected naming convention | Content that should be `tabs` gets mapped to `content-text`; assessment questions get scattered across pages instead of grouped; accordion content becomes flat text |

**The core issue:** The AI must *infer* structure from *unstructured* content. The document author knows the intended structure (this section is a page, these sub-sections are tabs, this block is a knowledge check) but has no way to communicate it.

### A.2 Proposed Solution: Template Marking System

Introduce a **template marking layer** that sits between document upload and AI processing. Before uploading, authors (or a pre-processing step) annotate the source document with structured markers that tell the AI exactly:

1. **Where pages begin and end** — page boundaries
2. **What template type** each page should use — eliminating template selection guesswork
3. **What components** each page contains — enabling multi-component pages
4. **Component hierarchy** — parent/child nesting (e.g., a `tabs` component containing `content-text` in each tab)
5. **Component-specific data shaping** — hints for what content goes into which component field

The markers serve as a **deterministic scaffold** — the AI still generates the actual content, but it no longer has to guess at structure.

### A.3 Marking Approaches (MVP + Future)

Three progressively sophisticated approaches:

#### Approach 1: In-Document Markers (MVP)
The author inserts plain-text markers directly into the DOCX. The `DocumentSplitter` (or a new `MarkedDocumentSplitter`) parses these markers to build a precise structural map before the LLM ever sees the content.

**Marker syntax example:**
```
[PAGE: tabs | title: Phishing Attack Vectors]
[COMPONENT: content-text]
Phishing is a form of social engineering...
[/COMPONENT]
[COMPONENT: accordion]
[ITEM: Spear Phishing]
Targeted attacks directed at specific individuals...
[/ITEM]
[ITEM: Whaling]
Attacks targeting senior executives...
[/ITEM]
[/COMPONENT]
[/PAGE]

[PAGE: final-assessment | title: Knowledge Check — Phishing]
[COMPONENT: final-assessment | passing_score: 80]
[QUESTION: mcq]
Which of the following is NOT a type of phishing?
[A] Spear Phishing [B] Whaling [C] Firewalling [D] Clone Phishing
[ANSWER: C]
[FEEDBACK: Firewalling is a network security measure, not a phishing technique.]
[/QUESTION]
[/COMPONENT]
[/PAGE]
```

**Advantages:**
- Zero UI changes — markers are just text in the DOCX
- Human-readable and editable
- Works with existing DOCX upload pipeline
- Deterministic parsing (regex-based, no LLM needed for structure)

**Disadvantages:**
- Authors must learn marker syntax
- Markers are visible in the source document (could be hidden via Word formatting)
- No visual preview of the resulting course structure

#### Approach 2: Sidecar Manifest (Mid-term)
Instead of inline markers, the author provides a separate JSON/YAML manifest file alongside the DOCX. The manifest references DOCX sections (by heading text or paragraph index) and maps them to the course structure.

**Manifest example:**
```json
{
  "version": "1.0",
  "source_document": "cybersecurity-awareness.docx",
  "course_title": "Cybersecurity Awareness for the Modern Workplace",
  "pages": [
    {
      "title": "Phishing Attack Vectors",
      "template_type": "tabs",
      "source_sections": ["Heading: Phishing Attack Vectors", "Heading: Spear Phishing", "Heading: Whaling"],
      "components": [
        {
          "component_type": "content-text",
          "source_section": "Heading: Phishing Attack Vectors"
        },
        {
          "component_type": "accordion",
          "items": [
            {"title": "Spear Phishing", "source_section": "Heading: Spear Phishing"},
            {"title": "Whaling", "source_section": "Heading: Whaling"}
          ]
        }
      ]
    }
  ]
}
```

**Advantages:**
- Clean separation — DOCX stays unchanged
- Machine-friendly format (easy to validate, auto-generate)
- Can be generated by a pre-upload wizard UI

**Disadvantages:**
- Two files to manage (DOCX + manifest)
- Source section references can break if DOCX headings change
- Harder for authors to create manually

#### Approach 3: Visual Template Marking UI (Long-term)
A pre-upload interface where the author:
1. Uploads the DOCX
2. Sees a preview of extracted sections
3. Drags sections into pages
4. Assigns template types from a dropdown
5. Configures component hierarchy visually
6. The system generates the manifest (Approach 2) automatically

This is the ideal UX but requires frontend work beyond the scope of the backend template marking system.

### A.4 Scope of the Template Marking FRD/TRD

The FRD and TRD should define:

1. **Marker Syntax Specification** — formal grammar for in-document markers (Approach 1), covering all 5 canonical template types plus their components
2. **MarkedDocumentParser** — a new service that:
   - Detects whether an uploaded DOCX contains markers
   - Parses markers into a `MarkedDocument` structure (pages, components, hierarchy)
   - Passes parsed structure to the breakdown step, bypassing LLM template selection
3. **Fallback Behavior** — when markers are absent or malformed, the existing heuristic/LLM pipeline runs unchanged
4. **Integration Points** — where the marker parser plugs into the existing Flow 10/11 pipeline
5. **Validation Rules** — structural validation of parsed markers (e.g., no overlapping pages, valid template types, component nesting rules)
6. **Error Reporting** — clear error messages when markers are malformed, referencing line numbers in the source DOCX
7. **Sidecar Manifest Schema** (Approach 2 planning) — JSON Schema for the manifest format

### A.5 Expected Outcomes

| Outcome | Measurement |
|---|---|
| Pages split correctly | 100% of marked pages produce exactly the intended page boundaries (vs. heuristic/LLM which is ~60-70% accurate for complex documents) |
| Component hierarchy preserved | Multi-component pages with nested components are generated correctly (currently impossible — all pages are single-component) |
| Template selection accurate | 100% of explicitly marked templates are used (vs. heuristic ~75-85% accuracy) |
| LLM cost reduction | No LLM calls needed for breakdown when markers are present (saves 1 LLM call per upload) |
| Backward compatible | Unmarked documents continue through the existing pipeline unchanged |

---

## Part B: AI Prompt — Build Detailed FRD

This prompt is designed to be given to an AI TPO/Architect to produce a complete Functional Requirements Document.

---

### Prompt: FRD for Template Marking System

```
You are a Technical Product Owner (TPO) specializing in AI-powered
e-learning authoring platforms. Your task is to write a detailed
Functional Requirements Document (FRD) for a **Template Marking System**
that enables deterministic page breakdown and component hierarchy
detection from uploaded DOCX files.

## CONTEXT

### Current System (What Exists)

Our e-learning backend (`app/services/ai/`) has a 7-step AI course
generation pipeline:

1. **Upload** (`POST /api/v1/ai/ingestions`) — Accepts PDF/DOCX/TXT/MD.
   `DocumentExtractor` uses python-docx to extract paragraphs with real
   style metadata (style_name, is_heading, heading_level).
   `DocumentSplitter` splits paragraphs into sections using heading styles
   or regex heuristics.

2. **Extract** — Each section is a flat dict: {index, heading,
   content_preview, char_count}. NO concept of component hierarchy or
   template types at this stage.

3. **Propose Breakdown** (`POST /ai/ingestions/{id}/propose-breakdown`) —
   `_heuristic_breakdown()` uses regex patterns (PAGE X —, Tab N —,
   Section N —, Question N) to detect parent/child relationships.
   `_call_llm_for_breakdown()` sends sections to an LLM with template
   schemas and asks it to propose pages. Template selection uses
   `FeatureDetector` (regex-based feature extraction) + `TemplateSelector`
   (8 heuristic scoring rules + rule arbitration).

4. **Review Plan** — User approves/rejects/modifies the page plan.

5. **Generate Course** — `CourseGenerator` creates content using
   template-specific agents (TextContentAgent, TabsAgent, AccordionAgent,
   AssessmentAgent). Model tier routing: SMALL templates (content-text)
   use phi3:mini; MID (accordion, tabs) use qwen2.5:7b; LARGE
   (final-assessment) use qwen2.5:7b.

6. **Poll Status** — Returns generated pages with components.

7. **Apply** — Transactional commit of CourseRecord + PageRecord +
   ComponentRecord to PostgreSQL.

### The Problem

When uploading "SB2-Cybersecurity Awareness for the Modern Workplace.docx"
(a typical corporate training document), the pipeline fails because:

**Page Splitting Failure:**
- The DOCX uses Word heading styles inconsistently
- `_heuristic_breakdown` regex patterns (PAGE X —, Tab N —) don't match
  the document's actual heading convention ("Module 1:", "Topic:", etc.)
- The LLM breakdown prompt has no structural hints — it receives flat
  section text and must guess where pages begin/end
- Result: sections are either over-split (every H2 becomes a page) or
  under-split (multiple logical pages merged into one)

**Component Hierarchy Failure:**
- The current pipeline produces exactly 1 component per page
- There is NO mechanism to specify: "this page has a content-text
  introduction, then an accordion with 5 items, then a key-takeaways
  callout"
- Nested components (e.g., tabs where each tab contains an image +
  content-text) are impossible
- The FeatureDetector detects has_callout and has_list but the breakdown
  doesn't use this for component planning — it only affects content
  generation later

**Template Selection Failure:**
- `TemplateSelector` heuristics rely on keyword matching: "quiz" →
  final-assessment, "compare" → tabs, "faq" → accordion
- The cybersecurity document uses domain-specific language ("knowledge
  check", "scenario exercise", "case study") that doesn't match the
  keyword lists
- `_suggest_template()` falls back to content-text for anything without
  clear keywords
- The LLM template selection (when used) has high variance — same
  document can produce different template assignments on re-runs

### The Proposed Solution

A **Template Marking System** that lets authors annotate their DOCX
with structured markers telling the AI:
1. Where pages begin/end
2. What template type each page uses
3. What components each page contains
4. Component hierarchy (parent/child nesting)
5. Component-specific configuration (tab titles, question stems, etc.)

### Existing Architecture to Integrate With

- **5 canonical template types:** content-text, tabs, accordion,
  click-reveal, final-assessment
- **89 component types** across 17 categories (seeded in
  `app/services/seed_component_types.py`)
- **DocumentExtractor** (`app/services/ai/document_extractor.py`) —
  preserves real paragraph styles from DOCX
- **DocumentSplitter** (`app/services/ai/document_splitter.py`) — 3
  splitting paths (structured, headings, heuristics)
- **AIIngestionJobRecord** — ORM model with extracted_sections (JSON),
  source_metadata (JSON), status state machine
- **FeatureDetector** — extracts ContentFeatures from text (regex-based,
  zero LLM)
- **TemplateSelector** — scores templates from features, rule
  arbitration, LLM refinement for ambiguous cases
- **CourseGenerator** — template-specific content generators with tier
  routing
- **Flow 10/11 Postman collection** — 7-step test flow

## YOUR TASK

Write a detailed FRD covering:

### 1. Marker Syntax Specification

Define a formal grammar for in-document markers (Approach 1: inline
text markers in the DOCX). The syntax must cover:

**Page markers:**
- `[PAGE: <template_type> | title: <page_title>]` ... `[/PAGE]`
- Optional attributes: `order`, `condition` (e.g., show-if-passed)

**Component markers:**
- `[COMPONENT: <component_type>]` ... `[/COMPONENT]`
- Nested components must be supported (components can contain other
  components)
- Optional attributes: `order`, `visibility`, `collapsed` (for accordion
  items)

**Component-item markers** (for list-type components):
- `[ITEM: <item_title>]` ... `[/ITEM]` — for tabs, accordion items,
  click-reveal items
- `[QUESTION: <type>]` ... `[/QUESTION]` — for assessment questions
- `[OPTION: <id> | correct: true/false]` ... `[/OPTION]` — for MCQ
  options

**Special markers:**
- `[LEARNING_OBJECTIVE]` ... `[/LEARNING_OBJECTIVE]`
- `[KEY_TAKEAWAY]` ... `[/KEY_TAKEAWAY]`
- `[CALLOUT: <type>]` ... `[/CALLOUT]` — for tip/warning/note boxes

**Escaping rules:**
- How to include literal `[PAGE:` text in content
- Case sensitivity
- Whitespace handling

### 2. MarkedDocumentParser Specification

Define a new service `MarkedDocumentParser` that:
- Scans extracted DOCX text for markers before the existing splitter runs
- Parses markers into a `MarkedDocument` structure:

```python
class MarkedPage:
    title: str
    template_type: str  # canonical type
    order: int
    components: list[MarkedComponent]
    source_paragraph_indices: list[int]

class MarkedComponent:
    component_type: str
    order_index: int
    items: list[MarkedItem]
    children: list[MarkedComponent]  # nested components
    raw_content: str  # text between [COMPONENT] and [/COMPONENT]
    source_paragraph_indices: list[int]

class MarkedItem:
    title: str
    content: str
    item_type: str  # "tab", "accordion-item", "question", etc.
    metadata: dict  # type-specific fields

class MarkedDocument:
    has_markers: bool
    pages: list[MarkedPage]
    unmarked_sections: list[dict]  # sections without markers → fallback pipeline
    parse_errors: list[ParseError]
```

- Validates marker structure:
  - No overlapping pages
  - Proper nesting (COMPONENT inside PAGE, ITEM inside COMPONENT)
  - Valid template types (against canonical whitelist)
  - Valid component types (against component_type registry)
  - Required attributes present
- Reports parse errors with DOCX paragraph references for user correction

### 3. Integration Points

Define exactly where `MarkedDocumentParser` plugs into the existing
pipeline:

**Ingestion (`ingestion_service.py`):**
- After `DocumentExtractor.extract_structured()` returns paragraphs
- Before `DocumentSplitter.split_structured()` runs
- If markers detected → `MarkedDocumentParser.parse()` → store
  `MarkedDocument` on `AIIngestionJobRecord.source_metadata`
- If no markers → existing pipeline unchanged

**Propose Breakdown (`ai_ingestion.py:_llm_propose_breakdown`):**
- Check `job.source_metadata` for `MarkedDocument`
- If present AND `has_markers=True`:
  - Skip `_heuristic_breakdown()` entirely
  - Skip `_call_llm_for_breakdown()` entirely
  - Convert `MarkedDocument.pages` directly to page plan format
  - Template types come from markers (no `TemplateSelector` needed)
  - Component hierarchy comes from markers (no LLM guessing)
  - Still run validation (coverage check, template whitelist)
- If absent → existing heuristic/LLM/rule-based pipeline unchanged

**Content Generation (`course_generator.py`):**
- If `MarkedDocument` has component hierarchy:
  - `_generate_page_content()` uses marked components instead of
    auto-detecting components
  - Each `MarkedComponent` generates one component in the output
  - Nested components are preserved in the generated output
  - The LLM is still used for content TEXT within components, but not
    for structure

### 4. State Machine Changes

Define new job statuses and transitions:
- `marked_detected` — markers found during extraction
- `marked_parsed` — markers successfully parsed (or `marked_parse_error`
  with error details)
- How "marker mode" vs. "normal mode" is tracked on the job

### 5. Validation Rules

Define structural validation that runs after marker parsing:
- Page-level: title present, template_type valid, at least 1 component
- Component-level: valid component_type, required fields per component
  type
- Hierarchy: max nesting depth (recommend 2: Page → Component →
  Sub-component)
- Assessment: at least 3 questions, passing_score 0-100, correct answer
  specified
- Cross-page: no duplicate page titles, order indices unique

### 6. Error Reporting Specification

Define the error format returned to the user when markers are malformed:
```json
{
  "status": "marked_parse_error",
  "errors": [
    {
      "code": "UNCLOSED_MARKER",
      "message": "PAGE marker opened at paragraph 12 but never closed",
      "location": {"paragraph_index": 12, "paragraph_text_preview": "[PAGE: tabs..."},
      "severity": "error"
    }
  ],
  "warnings": [...]
}
```

Error codes to define: UNCLOSED_MARKER, INVALID_TEMPLATE_TYPE,
INVALID_COMPONENT_TYPE, OVERLAPPING_PAGES, NESTING_VIOLATION,
MISSING_REQUIRED_ATTRIBUTE, DUPLICATE_PAGE_TITLE, EMPTY_COMPONENT

### 7. Backward Compatibility

- Unmarked documents MUST pass through existing pipeline unchanged
- Existing tests (834 tests in 20 suites) MUST continue to pass
- The marker parser MUST be a no-op when no markers are detected

### 8. Sidecar Manifest JSON Schema (Phase 2 Planning)

Even though Phase 1 implements in-document markers, define the JSON
Schema for the Phase 2 sidecar manifest format. This ensures the
internal data model supports both approaches.

## DELIVERABLE FORMAT

Write the FRD as a structured markdown document with these sections:
1. Executive Summary
2. Current State Analysis (pipeline walkthrough, failure modes)
3. Functional Requirements (use cases, user stories)
4. Marker Syntax Specification (formal grammar)
5. MarkedDocumentParser API Specification
6. Integration Architecture (sequence diagrams, data flow)
7. State Machine Specification
8. Validation Rules
9. Error Handling
10. Backward Compatibility Requirements
11. Sidecar Manifest JSON Schema (Phase 2)
12. Acceptance Criteria (per user story)
13. Open Questions & Risks

## CONSTRAINTS

- Zero breaking changes to existing API contracts (all 44 AI endpoints
  must work as before)
- All 834 existing tests must pass
- The Postman collection (65/82 passing) must not regress
- Marker syntax must be human-readable and editable in Word
- Parser must run in <50000ms for a 50-page document
- Must support the 5 canonical template types fully; the 89 component
  types partially (at least the ones used by the 5 templates)
- Must work with the existing `AIIngestionJobRecord` ORM model (no new
  tables for MVP)

## REFERENCE FILES

Study these files before writing the FRD:
- `app/routers/ai_ingestion.py` — full ingestion + breakdown logic
- `app/services/ai/ingestion_service.py` — upload + extraction
- `app/services/ai/document_extractor.py` — DOCX/PDF extraction
- `app/services/ai/document_splitter.py` — section boundary detection
- `app/services/ai/feature_detector.py` — ContentFeatures extraction
- `app/services/ai/template_selector.py` — heuristic template scoring
- `app/services/ai/course_generator.py` — content generation + apply
- `app/services/ai/template_contracts.py` — JSON schemas + business rules
- `app/models/ai_models.py` — AIIngestionJobRecord definition
- `docs/postman_progress.md` — validation results, known failures
- `docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-016_enriched.md`
- `docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-017_enriched.md`
- `docs/AI_Implemenation/00_User_StoriesUseCases/US-AI-019_GENERATE_FULL_COURSE_FROM_FILE.md`
```

---

## Part C: AI Prompt — Build Detailed TRD

This prompt is designed to be given to an AI Architect/Developer to produce a complete Technical Requirements Document, building on the FRD above.

---

### Prompt: TRD for Template Marking System

```
You are a Senior AI Architect / Backend Engineer on an e-learning
platform built with FastAPI, PostgreSQL, SQLAlchemy (async), Redis,
Redpanda (Kafka), and an LLM Gateway (MCP protocol). Your task is to
write a detailed Technical Requirements Document (TRD) for implementing
the **Template Marking System** — a deterministic text-marker parser
that enables page breakdown and component hierarchy detection from
annotated DOCX files, eliminating LLM guesswork from structural decisions.

## CONTEXT

### The Pipeline (Flow 10/11)

```
Upload DOCX
  → DocumentExtractor (python-docx, preserves real heading styles)
  → DocumentSplitter (3 paths: structured by heading styles, markdown
     headings, regex heuristics)
  → Sections[] (flat list: {index, heading, content_preview, char_count})
  → _llm_propose_breakdown()
      → _heuristic_breakdown() [regex parent/child detection]
      → _call_llm_for_breakdown() [LLM fallback]
      → _rule_based_breakdown() [one-section-one-page ultimate fallback]
  → PagePlan[] (proposed pages with titles + template types)
  → User reviews/approves plan
  → CourseGenerator._generate_pages()
      → TemplateTierRouter: SMALL(template) → phi3:mini,
        MID → qwen2.5:7b, LARGE → qwen2.5:7b
      → StreamManager.fan_out_pages() [Redis Streams or asyncio.gather]
      → Template-specific agent generates content
  → CourseGenerator.apply_generated_course()
      → CourseRecord + PageRecord + ComponentRecord persisted
```

### The Gap

Between "DocumentSplitter produces flat sections" and "Page plan with
template types", the system has NO structured input. Everything is
inferred: page boundaries, template types, component hierarchy. For
complex documents (cybersecurity training, compliance courses,
technical labs), inference fails ~30-40% of the time.

### The Solution

Insert a **MarkedDocumentParser** between extraction and breakdown.
When the DOCX contains template markers (special text annotations),
the parser produces a deterministic `MarkedDocument` that the breakdown
step uses directly — zero LLM calls, zero heuristics, 100% accuracy.

## YOUR TASK

Write a detailed TRD covering:

### 1. MarkedDocumentParser — Class Design

Provide the complete Python class design:

```python
class MarkedDocumentParser:
    """Parses template markers from extracted DOCX paragraphs.

    Scans paragraphs for [PAGE: ...], [COMPONENT: ...], [ITEM: ...],
    [QUESTION: ...] markers and builds a deterministic MarkedDocument
    with page boundaries, component hierarchy, and template assignments.

    When no markers are detected, returns MarkedDocument(has_markers=False)
    so the existing pipeline runs unchanged.
    """

    # Marker regex patterns (compiled at class level for performance)
    _PAGE_OPEN: ClassVar[re.Pattern]
    _PAGE_CLOSE: ClassVar[re.Pattern]
    _COMPONENT_OPEN: ClassVar[re.Pattern]
    _COMPONENT_CLOSE: ClassVar[re.Pattern]
    _ITEM_OPEN: ClassVar[re.Pattern]
    _ITEM_CLOSE: ClassVar[re.Pattern]
    # ... etc.

    def __init__(self, component_registry: ComponentTypeRegistry | None = None): ...
    def parse(self, paragraphs: list[dict]) -> MarkedDocument: ...
    def has_markers(self, paragraphs: list[dict]) -> bool: ...  # fast pre-check
    def validate(self, doc: MarkedDocument) -> list[ParseError]: ...
```

Specify:
- Exact regex patterns for each marker type
- How attributes are parsed (key: value pairs, optional vs required)
- How nested markers are tracked (stack-based parsing)
- How unmarked content between markers is handled
- Performance characteristics (<50ms for 50-page doc)

### 2. Data Structures

Define the exact dataclasses/Pydantic models:

```python
@dataclass
class MarkedPage:
    title: str
    template_type: str
    order: int
    components: list[MarkedComponent]
    source_paragraph_indices: list[int]
    attributes: dict[str, str]  # page-level attributes from marker

@dataclass
class MarkedComponent:
    component_type: str
    order_index: int
    items: list[MarkedItem]
    children: list[MarkedComponent]
    raw_content: str
    source_paragraph_indices: list[int]
    attributes: dict[str, str]

@dataclass
class MarkedItem:
    title: str
    content: str
    item_type: str  # "tab" | "accordion-item" | "question" | "option"
    order_index: int
    metadata: dict[str, Any]
    source_paragraph_indices: list[int]

@dataclass
class MarkedDocument:
    has_markers: bool
    source_filename: str
    pages: list[MarkedPage]
    unmarked_sections: list[dict]  # sections without markers
    parse_errors: list[ParseError]
    warnings: list[str]
    metadata: dict[str, Any]

@dataclass
class ParseError:
    code: str  # error code from registry
    message: str
    location: ParseLocation
    severity: Literal["error", "warning"]

@dataclass
class ParseLocation:
    paragraph_index: int
    line_number: int | None
    marker_type: str | None
    context_preview: str  # first 100 chars of the offending text
```

Specify serialization (to_dict / from_dict) for storing on
`AIIngestionJobRecord.source_metadata`.

### 3. Marker Syntax Formal Specification

Provide the complete formal grammar (EBNF or similar):

```ebnf
document      = { unmarked_content | page_marker } ;
page_marker   = page_open, { component_marker | unmarked_content }, page_close ;
page_open     = "[PAGE:", template_type, {attribute}, "]" ;
page_close    = "[/PAGE]" ;
template_type = "content-text" | "tabs" | "accordion" | "click-reveal"
              | "final-assessment" | "welcome" | "summary" ;
attribute     = identifier, ":", value ;
component_marker = component_open, { item_marker | unmarked_content
                   | component_marker }, component_close ;
component_open  = "[COMPONENT:", component_type, {attribute}, "]" ;
component_close = "[/COMPONENT]" ;
item_marker   = item_open, unmarked_content, item_close ;
item_open     = "[ITEM:", text, {attribute}, "]" ;
item_close    = "[/ITEM]" ;
question_marker = question_open, { option_marker }, question_close ;
question_open = "[QUESTION:", question_type, {attribute}, "]" ;
question_close = "[/QUESTION]" ;
option_marker = "[OPTION:", option_id, {attribute}, "]", text, "[/OPTION]" ;
```

Specify:
- Case sensitivity rules
- Whitespace normalization
- Escaping mechanism for literal brackets
- Maximum nesting depth
- Reserved attribute names per marker type
- How comment markers work (`[//]: # (comment)`)

### 4. Integration Architecture

#### 4.1 Ingestion Service Changes

Specify exactly what changes in `AIIngestionService.create_job()`:

```python
# After DocumentExtractor.extract_structured() returns paragraphs
# Before DocumentSplitter.split_structured() runs

parser = MarkedDocumentParser()
if parser.has_markers(paragraphs):
    marked_doc = parser.parse(paragraphs)
    if marked_doc.parse_errors:
        # Store errors, let user fix and re-upload
        job.extracted_sections = None
        job.source_metadata = {
            "marked_document": marked_doc.to_dict(),
            "marker_status": "parse_error",
        }
        job.status = "marked_parse_error"
    else:
        # Success — skip DocumentSplitter, use marked structure
        job.source_metadata = {
            "marked_document": marked_doc.to_dict(),
            "marker_status": "parsed",
        }
        job.status = "analyzed"  # Standard status, but with marked_document set
        # extracted_sections is derived from marked_document
        job.extracted_sections = _marked_doc_to_sections(marked_doc)
else:
    # No markers — existing pipeline unchanged
    sections = splitter.split_structured(paragraphs, filename)
    job.extracted_sections = [s.to_dict() for s in sections]
```

#### 4.2 Breakdown Changes

Specify exactly what changes in `_llm_propose_breakdown()`:

```python
async def _llm_propose_breakdown(sections, max_pages=50):
    # NEW: Check for marked document first
    marked_doc = _get_marked_document_from_job()
    if marked_doc and marked_doc.has_markers:
        return _convert_marked_to_plan(marked_doc)  # Deterministic, no LLM

    # Existing pipeline unchanged below this line
    try:
        heuristic_pages = _heuristic_breakdown(sections, max_pages)
        # ... rest unchanged
```

#### 4.3 Content Generation Changes

Specify what changes in `CourseGenerator._generate_page_content()`:

```python
def _generate_page_content(self, page, options, index, features=None):
    # NEW: Check for marked components
    marked_page = page.get("_marked_page")  # Passed through from plan
    if marked_page and marked_page.components:
        return self._generate_from_marked_components(
            marked_page, options, index
        )

    # Existing template dispatch unchanged below
    template_type = page.get("template_type", "text-content")
    # ...
```

#### 4.4 Database Changes

Specify what (if anything) changes in `AIIngestionJobRecord`:
- `source_metadata` JSON field — now includes optional `marked_document`
  key
- `extracted_sections` JSON field — when markers present, derived from
  marked_document rather than splitter output
- New optional statuses: `marked_parse_error`
- NO new tables needed (marked_document serializes to existing JSON
  columns)

### 5. Model Escalation Chain Changes

Specify how the model escalation chain (`_get_breakdown_model_chain()`)
changes:
- When `marked_document` is present: NO model calls at all — the chain
  is bypassed
- When `marked_document` is absent: existing chain unchanged
- Configuration: new env var `AI_MARKER_MODE` (values: `enabled`,
  `disabled`, `strict` — strict mode rejects uploads without markers)

### 6. Validation Engine Integration

Specify how `MarkedDocumentParser.validate()` works:

- Schema validation: every `template_type` must be in canonical whitelist
- Component validation: every `component_type` must be a valid type
- Structural validation:
  - Pages cannot overlap (same paragraph in 2 pages)
  - Components must be fully contained within their parent page
  - Items must be fully contained within their parent component
  - Max nesting depth: 2 (Page → Component → Sub-component)
- Content validation:
  - final-assessment pages must have ≥3 questions
  - Each MCQ question must have ≥2 options, exactly 1 correct
  - tabs must have 2-6 items
  - accordion must have 2-20 items
- Cross-reference validation:
  - No duplicate page titles
  - Source paragraph coverage: all marked paragraphs accounted for
  - Order indices unique within parent

### 7. Error Handling Strategy

Define the error handling flow:

```
Markers detected → Parse
  ├─ Success → Store marked_document, set status="analyzed"
  ├─ Warnings only → Store with warnings, set status="analyzed"
  │   (e.g., "Empty component on page 3 — will be skipped")
  └─ Errors → Store errors, set status="marked_parse_error"
      └─ User sees errors in API response
          ├─ Fix markers in DOCX → Re-upload
          └─ OR: Remove markers → Fall through to existing pipeline
```

Error severity levels:
- **error**: Blocks processing (unclosed marker, invalid template type)
- **warning**: Non-blocking (empty component, duplicate title, missing
  optional attribute)

Error response format (from API):
```json
{
  "status": "marked_parse_error",
  "job_id": "abc123",
  "marker_status": "parse_error",
  "parse_errors": [
    {
      "code": "UNCLOSED_MARKER",
      "message": "[PAGE: tabs] opened at paragraph 12 but not closed by paragraph 45",
      "location": {
        "paragraph_index": 12,
        "marker_type": "PAGE",
        "context_preview": "[PAGE: tabs | title: Phishing Attack Vectors]"
      },
      "severity": "error",
      "suggestion": "Add [/PAGE] after paragraph 44 to close this page."
    }
  ],
  "warnings": [],
  "total_errors": 1
}
```

### 8. Performance Requirements

- `has_markers()` pre-check: <5ms (single regex scan over paragraph
  count)
- `parse()` for 50-page document (200 paragraphs): <50ms
- `validate()` for 50-page document: <10ms
- Memory: MarkedDocument <1MB for 50-page document
- No database migrations required (uses existing JSON columns)
- No new dependencies (regex + dataclasses only, both stdlib)

### 9. Test Strategy

Define the test suite:

**Unit Tests (new file: tests/run_marked_parser_tests.py):**
- Test each marker type in isolation (PAGE, COMPONENT, ITEM, QUESTION,
  OPTION)
- Test nested markers (Page → Component → Item)
- Test multi-component pages
- Test assessment pages with full question/option structure
- Test unmarked documents (parser returns has_markers=False)
- Test malformed markers (unclosed, invalid type, bad nesting)
- Test escaping (literal `[PAGE:` in content)
- Test attribute parsing (valid, missing required, invalid values)
- Test all 5 canonical template types
- Test edge cases: empty document, markers-only document, deeply nested
  (3+ levels → should warn)

**Integration Tests:**
- Test full Flow 10/11 with a marked DOCX (create test fixture)
- Test full Flow 10/11 with an unmarked DOCX (no regression)
- Test marked → breakdown skip (verify no LLM call made)
- Test marked → content generation with component hierarchy
- Test error flow: upload marked doc with errors → see error response →
  fix → re-upload → success

**Regression Tests:**
- All 834 existing tests must pass unchanged
- Postman collection Flow 10/11 must pass with unmarked documents
- Postman collection Flow 10/11 must pass with marked test document

### 10. Feature Flags & Configuration

New environment variables:
```bash
# Master switch for template marking
AI_TEMPLATE_MARKING_ENABLED=true

# Strict mode: reject uploads without markers
AI_TEMPLATE_MARKING_STRICT_MODE=false

# Max nesting depth for components (default: 2)
AI_TEMPLATE_MARKING_MAX_NESTING=2

# Max pages per marked document
AI_TEMPLATE_MARKING_MAX_PAGES=50
```

Feature flag integration with existing `get_ai_config()`:
```python
@dataclass
class AIConfig:
    # ... existing fields ...
    template_marking_enabled: bool = False
    template_marking_strict_mode: bool = False
    template_marking_max_nesting: int = 2
    template_marking_max_pages: int = 50
```

### 11. Migration Path

Phase 1 (this TRD):
- In-document text markers (Approach 1)
- `MarkedDocumentParser` with full validation
- Integration into Flow 10/11 pipeline
- Zero new dependencies, zero new DB tables

Phase 2 (future):
- Sidecar manifest JSON (Approach 2) — `ManifestParser` that produces
  the same `MarkedDocument` structure
- The `MarkedDocument` dataclass is the canonical internal
  representation; both parsers target it

Phase 3 (future):
- Visual template marking UI (Approach 3) — generates the sidecar
  manifest
- Template library: saved marking patterns for common course types
  (compliance training, technical lab, soft skills)
- AI-assisted marking: LLM suggests markers, human reviews

### 12. Security Considerations

- Markers are plain text — no code execution risk
- `ast.literal_eval()` should NOT be used for attribute parsing; use
  simple string splitting
- Max document size unchanged (50MB)
- Max pages per document unchanged (50, configurable)
- No user input from markers reaches the LLM in an unvalidated state
  — all template/component types are validated against whitelists

### 13. Observability

- Log when markers are detected (INFO level, includes page count)
- Log when markers are absent (DEBUG level)
- Log parse errors with paragraph indices (WARNING level)
- Metrics: `marked_documents_total`, `marked_parse_errors_total`,
  `marked_parse_duration_ms`
- Trace: `marker_status` tag on ingestion spans

## DELIVERABLE FORMAT

Write the TRD as a structured markdown document with these sections:
1. Technical Summary
2. Architecture Overview (diagram showing new component in pipeline)
3. Data Structures (complete class definitions)
4. Marker Syntax Formal Specification (EBNF grammar)
5. MarkedDocumentParser — Complete Class Design
6. Integration Architecture (with code-level change specifications)
7. Database Impact Analysis
8. API Changes (new response fields, new error codes)
9. Configuration & Feature Flags
10. Error Handling Specification
11. Performance Budget
12. Test Strategy (test cases, fixtures, coverage targets)
13. Migration Path (Phase 1 → 2 → 3)
14. Security Review
15. Observability & Monitoring
16. Implementation Sequence (file-by-file change order)
17. Rollback Plan

## CONSTRAINTS

- Zero new Python dependencies beyond stdlib
- Zero database migrations (uses existing JSON columns on
  AIIngestionJobRecord)
- Zero breaking API changes (all 44 AI endpoints unchanged for unmarked
  documents)
- Existing test suite (834 tests) must pass without modification
- Postman collection (Flow 10/11) must work for both marked and unmarked
  documents
- Parser must handle all 5 canonical template types with their full
  component schemas
- Must support the component hierarchy patterns used by the 5 canonical
  templates:
  - content-text: main content + optional callout + optional key_points
  - tabs: tabs component with 2-6 tab items
  - accordion: accordion component with 2-20 items
  - click-reveal: accordion component with 2-10 items (reuses accordion
    component type)
  - final-assessment: assessment component with 3-50 questions
- The TRD must be implementable in <5 working days by a senior backend
  engineer

## REFERENCE FILES

Study these files before writing the TRD:
- `app/routers/ai_ingestion.py` — ingestion + breakdown endpoints
  (1216 lines)
- `app/services/ai/ingestion_service.py` — upload + extraction (269
  lines)
- `app/services/ai/document_extractor.py` — DOCX/PDF extraction with
  style preservation
- `app/services/ai/document_splitter.py` — 3-path section splitting
  (318 lines)
- `app/services/ai/feature_detector.py` — ContentFeatures (362 lines)
- `app/services/ai/template_selector.py` — heuristic scoring +
  arbitration (467 lines)
- `app/services/ai/course_generator.py` — generation + apply (1215
  lines)
- `app/services/ai/template_contracts.py` — JSON schemas + business
  rules (402 lines)
- `app/services/ai/agents/template_agents.py` — template-specific
  content generators
- `app/services/ai/template_tier_router.py` — SMALL/MID/LARGE tier
  routing
- `app/services/ai/fanout/__init__.py` — Redis Streams parallel
  generation
- `app/models/ai_models.py` — AIIngestionJobRecord ORM definition
- `app/models/component_type.py` — ComponentType ORM (89 types)
- `app/services/ai/config.py` — AIConfig dataclass
- `docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-016_enriched.md`
- `docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-017_enriched.md`
- `docs/AI_Implemenation/00_User_StoriesUseCases/US-AI-019_GENERATE_FULL_COURSE_FROM_FILE.md`
```

---

## Part D: Summary — What to Build

### D.1 The Core Insight

The AI pipeline currently does two jobs that should be separated:

| Job | Who Should Do It | Who Currently Does It |
|---|---|---|
| **Structure** (page boundaries, template types, component hierarchy) | Document author (deterministic, intentional) | LLM (probabilistic, unreliable) |
| **Content** (text, questions, examples, feedback) | LLM (generative, creative) | LLM (correct role) |

The template marking system separates these concerns: the **author defines structure** via markers, and the **LLM fills in content** within that structure.

### D.2 Implementation Priority

**P0 (MVP — 5 days):**
1. `MarkedDocumentParser` class with PAGE, COMPONENT, ITEM markers
2. Integration into ingestion pipeline (marker detection → parse → store on job)
3. Breakdown bypass when markers present (skip LLM, convert marked doc to plan)
4. Support for all 5 canonical template types
5. Error reporting for malformed markers
6. Unit tests + integration tests

**P1 (Week 2):**
7. QUESTION/OPTION markers for assessment pages
8. Nested component support (Page → Component → Sub-component)
9. Content generation from marked components (preserve hierarchy)
10. Postman collection updates for marked document flow

**P2 (Phase 2):**
11. Sidecar manifest JSON format
12. ManifestParser that targets same MarkedDocument structure
13. Validation rules engine

### D.3 Key Design Decisions Embedded in the Prompts

1. **Inline markers over sidecar manifest for MVP** — lower barrier to entry, no file management overhead, works with existing upload endpoint
2. **MarkedDocument as canonical internal format** — both inline markers and future sidecar manifests produce the same data structure
3. **No new database tables** — MarkedDocument serializes to existing JSON columns on AIIngestionJobRecord
4. **No new dependencies** — regex + dataclasses only (both Python stdlib)
5. **Complete backward compatibility** — unmarked documents flow through existing pipeline unchanged
6. **Zero LLM calls for structure when markers present** — cost saving + determinism
7. **Stack-based parsing for nested markers** — handles arbitrary nesting depth (validated to max 2 levels)
8. **Error-first UX** — parse errors block processing with specific fix suggestions; warnings allow processing to continue

---

*Document prepared for AI TPO/Architect/Developer handoff. The prompts in Parts B and C are self-contained and can be given directly to an AI agent for FRD and TRD generation respectively.*
