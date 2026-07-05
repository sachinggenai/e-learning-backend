# TRD: Course Generation Quality — Complete Architecture

> **Doc ID:** TRD-CGQ-2026-07-05  
> **Status:** Production Blocker — P0  
> **Audience:** Third-party reviewers, AI developers (zero codebase access assumed)  
> **Dependencies:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Ollama (phi3:mini, qwen2.5:7b), MCP Gateway (:8004), PostgreSQL 16

---

## 1. Problem Statement

### 1.1 Observed Defects

| # | Symptom | Severity |
|---|---|---|
| D1 | 9/10 pages assigned `content-text` template — interactive templates (`accordion`, `tabs`, `click-reveal`) never selected | Blocker |
| D2 | `final-assessment` always uses mock fallback: 1 generic MCQ with placeholder options | Blocker |
| D3 | Pages have flat structure — exactly 1 component per page, no multi-component hierarchy | High |
| D4 | DOCX extraction produces garbled `content_preview` — multiple sections show identical text | Blocker |
| D5 | Template selection LLM (`phi3:mini`, 2B params) defaults to safest choice when input is ambiguous | High |
| D6 | Content generation provider reported as `"anthropic"` but actual provider is Ollama — routing confusion | Medium |

### 1.2 Business Impact
- E-learning courses lack interactivity (no tabs, accordions, reveal elements)
- Assessments are non-functional (1 generic question vs 5+ expected)
- Course structure is flat (no component hierarchy for progressive disclosure)
- Re-work on every generated course to manually fix template assignments

---

## 2. Current Architecture

### 2.1 System Context Diagram

```
┌──────────┐    ┌──────────────┐    ┌───────────────┐    ┌──────────────┐
│  Client   │───▶│  FastAPI      │───▶│  MCP Gateway   │───▶│  Ollama       │
│ (Postman) │    │  :8000        │    │  :8004         │    │  :11434       │
└──────────┘    └──────┬───────┘    └───────┬───────┘    │ phi3:mini     │
                       │                    │            │ qwen2.5:7b    │
                       ▼                    │            └──────────────┘
              ┌──────────────┐    ┌────────┴────────┐
              │  PostgreSQL   │    │  MCP Domain      │
              │  :5432        │    │  Tools :8005     │
              └──────────────┘    └─────────────────┘
```

### 2.2 Pipeline Data Flow

```
Stage 1: Upload          Stage 2: Extract         Stage 3: Split           Stage 4: Propose          Stage 5: Generate         Stage 6: Apply
┌──────────┐          ┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│ upload_   │          │ Document     │       │ _extract     │       │ _llm_propose │       │ _generate    │       │ apply_gen    │
│ document  │─────────▶│ Extractor    │──────▶│ _text()      │──────▶│ _breakdown() │──────▶│ _pages_with  │──────▶│ erated_      │
│ ()        │          │ .extract()   │       │              │       │              │       │ _llm()       │       │ course()     │
└──────────┘          └──────────────┘       └──────────────┘       └──────────────┘       └──────────────┘       └──────────────┘
     │                      │                      │                      │                      │                      │
     ▼                      ▼                      ▼                      ▼                      ▼                      ▼
 ai_ingestion      document_              ingestion_             ai_ingestion          course_                course_
 _jobs row          extractor.py          service.py:180         .py:488               generator.py:558       generator.py:319
                    (python-docx)         (blank-line split)     (phi3:mini via         (ContentGenerator      (PageRecord
                                                                MCP Gateway)           Agent + StreamMgr)     insert)
```

### 2.3 Source Files — Complete Map

```
app/
├── routers/
│   └── ai_ingestion.py           # Pipeline endpoints (upload, propose, review, generate, apply)
├── services/ai/
│   ├── ingestion_service.py      # Upload + text extraction + section splitting
│   ├── document_extractor.py     # PDF/DOCX text extraction via pdfplumber/python-docx
│   ├── course_generator.py       # Course generation + mock fallback + apply + fingerprint
│   ├── template_contracts.py     # Template business rules + JSON schemas (5 types)
│   ├── config.py                 # AI config (model tiers, API keys, feature flags)
│   ├── llm_client.py             # LLM provider abstraction (Anthropic / Mock / Ollama)
│   ├── agents/
│   │   ├── content_generator_agent.py  # AGT-07: LLM page content generation
│   │   ├── planner_agent.py           # AGT-06: Page plan optimization
│   │   └── template_selector_agent.py # AGT-08: Template type selection
│   ├── fanout/
│   │   └── __init__.py           # StreamManager: parallel page generation
│   ├── mcp_client/
│   │   └── llm_gateway_client.py # MCP Gateway HTTP client
│   └── json_repair.py            # 12-strategy JSON repair pipeline
├── models/
│   ├── ai_models.py              # AIIngestionJobRecord (dual state machine doc)
│   ├── page_component.py         # PageRecord, ComponentRecord
│   └── persisted_course.py       # TemplateDefinition (template schemas in DB)
└── schemas/
    └── ai_session.py             # CreateSessionRequest/Response
```

---

## 3. Root Cause Analysis — Stage by Stage

### 3.1 Stage 2-3: Document Extraction & Section Splitting

**Files:** `document_extractor.py`, `ingestion_service.py:180`

**Current code path:**
```
upload_document() 
  → AIIngestionService.create_job()
    → DocumentExtractor.extract(file_path, mime)
      → _extract_docx() → python-docx → plain text (paragraphs joined with \n)
    → _extract_text(text, filename, "md")
      → splits by blank lines or markdown headings
      → each section gets: {heading, content_preview[:500], char_count}
```

**Problem:** PowerPoint-sourced DOCX files have no blank-line separators between slides.
`_extract_text()` treats the entire document as one contiguous block. All sections get
the same `heading` (filename) and identical `content_preview[:500]` (first 500 chars).

**Evidence (SB2 docx):**
```
Section 0: heading="SB2-Cybersec...docx", preview="Tab 1\n—Page -1 Welcome..."
Section 1: heading="SB2-Cybersec...docx", preview="Welcome to Cybersecurity Awareness\nExplore..."
Section 2: heading="SB2-Cybersec...docx", preview="Welcome to Cybersecurity Awareness\nExplore..."  ← IDENTICAL to 1
Section 3: heading="SB2-Cybersec...docx", preview="Welcome to Cybersecurity Awareness\nExplore..."  ← IDENTICAL to 1
```

**Line numbers:** `ingestion_service.py:180-210` (`_extract_text`), `document_extractor.py:50-85` (`_extract_docx`)

### 3.2 Stage 4: Template Selection (propose-breakdown)

**Files:** `ai_ingestion.py:488-604` (`_llm_propose_breakdown`, `_call_llm_for_breakdown`)

**Current code path:**
```
POST /ingestions/{id}/propose-breakdown
  → _llm_propose_breakdown(sections, max_pages)
    → _call_llm_for_breakdown(sections, max_pages)
      → Builds prompt with template_schemas + RAG context + section text
      → POST http://localhost:8004/v1/chat/completions {"model": "phi3:mini"}
      → Parses JSON response
    → Fallback: _rule_based_breakdown() if LLM fails
```

**Problems:**

| ID | Line | Problem | Consequence |
|---|---|---|---|
| P1 | 576 | `model: "phi3:mini"` — hardcoded, 2B params | Underpowered for classification |
| P2 | 551-568 | Prompt sends garbled section previews from Stage 3 | LLM sees noise, defaults to safest |
| P3 | 514 | `_rule_based_breakdown()` always assigns `content-text` | Fallback never uses interactive templates |
| P4 | 565-567 | Expected JSON: `{title, template_type, rationale, source_section_ids, order}` | No `component_structure` field — no multi-component detection |
| P5 | 591-600 | Truncated JSON repair is fragile | May lose last sections on token overflow |
| P6 | 504 | No retry with different model if phi3 fails | Single point of failure |

### 3.3 Stage 5: Content Generation (generate-course)

**Files:** `course_generator.py:529-647` (`_generate_pages`, `_generate_pages_with_llm`, `_generate_page_content`)

**Current code path:**
```
POST /generate-course
  → CourseGenerator.start_generation()
    → _generate_pages(pages, options)
      → _generate_pages_with_llm()  [LLM path]
        → ContentGeneratorAgent.generate_page() × N (parallel via StreamManager)
      → _generate_page_content()    [Mock fallback per page]
```

**Problems:**

| ID | Line | Problem | Consequence |
|---|---|---|---|
| G1 | 667-678 | Mock `content-text`: generic placeholder content | "This section covers key concepts related to..." |
| G2 | 724-743 | Mock `final-assessment`: 1 MCQ with placeholder options | `"method": "inline_mock"` in metadata |
| G3 | 595-603 | Same `ContentGeneratorAgent` for all template types | No template-specific generation logic |
| G4 | 577 | Provider detection: `LLMProvider.ANTHROPIC if cfg.anthropic_api_key else LLMProvider.MOCK` | Ollama routed through "anthropic" provider label |
| G5 | 637-647 | Failed pages silently use mock fallback | No alert when LLM generation fails |
| G6 | 589 | `max_retries=3` but same prompt each retry | Repeated failures with no prompt improvement |

### 3.4 Root Cause Summary

```
                    ┌──────────────────────────────────────┐
                    │  ROOT CAUSE CHAIN                      │
                    │                                       │
                    │  Garbled sections ─────────────────┐  │
                    │  (DOCX→text lost structure)        │  │
                    │       │                            │  │
                    │       ▼                            │  │
                    │  phi3:mini defaults to safest ───┐ │  │
                    │  (content-text for all pages)     │ │  │
                    │       │                           │ │  │
                    │       ▼                           │ │  │
                    │  Single-agent generation ─────────┤ │  │
                    │  (no template-specific logic)     │ │  │
                    │       │                           │ │  │
                    │       ▼                           │ │  │
                    │  Assessment mock fallback ────────┘ │  │
                    │  (LLM can't generate MCQ JSON)      │  │
                    │       │                              │  │
                    │       ▼                              │  │
                    │  Flat single-component pages ◄──────┘  │
                    │  (no component hierarchy detection)    │
                    └──────────────────────────────────────┘
```

---

## 4. Proposed Architecture — High-Level Design

### 4.1 Architecture Principle: Heuristics-First, LLM-Enhanced

```
┌─────────────────────────────────────────────────────────────────────┐
│                    REVISED PIPELINE                                  │
│                                                                     │
│  Upload → Extract → Semantic Split → Feature Detect → Score → Gen   │
│            │            │               │            │        │     │
│            ▼            ▼               ▼            ▼        ▼     │
│       python-docx   LLM-pass      Heuristics    Rules     Template- │
│       + paragraph   (optional)    Engine        Engine    Specific  │
│       styles        for semantic  ZERO LLM      ZERO LLM  Agents    │
│                     boundaries    dependency    dependency  + Tier   │
│                                                                     │
│  KEY INSIGHT: Stages 3-5 work with ZERO LLM. LLM only enhances.     │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Diagram

```
┌─────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ DocumentSplitter │   │ FeatureDetector   │   │ TemplateSelector  │
│ (NEW)            │   │ (NEW)             │   │ (REFACTOR)        │
├─────────────────┤   ├──────────────────┤   ├──────────────────┤
│ + split(text)    │──▶│ + detect(text,    │──▶│ + score(features) │
│   → Section[]    │   │   pos, total)     │   │   → Template[]   │
│                  │   │   → Features      │   │                  │
│ Uses:            │   │                  │   │ Uses:            │
│ - paragraph      │   │ Purely regex +   │   │ - HEURISTICS     │
│   styles (DOCX)  │   │ counting — no    │   │   dict           │
│ - heading        │   │ external calls   │   │ - LLM (optional) │
│   detection      │   │                  │   │   for ambiguous  │
│ - LLM semantic   │   │                  │   │   cases only     │
│   (optional)     │   │                  │   │                  │
└─────────────────┘   └──────────────────┘   └──────────────────┘
                                                      │
                                                      ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ ModelTierRouter   │   │ TemplateAgents    │   │ ComponentBuilder  │
│ (REFACTOR)        │   │ (NEW)             │   │ (NEW)             │
├──────────────────┤   ├──────────────────┤   ├──────────────────┤
│ + resolve(        │──▶│ Per-template      │──▶│ + build(template, │
│   template_type,  │   │ agents:           │   │   features)       │
│   available_      │   │ - TextAgent       │   │   → Components[] │
│   models)         │   │ - TabsAgent       │   │                  │
│   → model_id      │   │ - AccordionAgent  │   │ Uses feature     │
│                  │   │ - RevealAgent     │   │ detection to     │
│ Uses:            │   │ - AssessmentAgent │   │ determine:       │
│ - MODEL_TIER      │   │                  │   │ - sub-components │
│   map             │   │ Each agent:      │   │ - callout boxes  │
│ - available       │   │ - template schema│   │ - key takeaways  │
│   models list     │   │ - few-shot ex.   │   │ - media refs     │
└──────────────────┘   │ - source content │   └──────────────────┘
                       │ - course context │
                       └──────────────────┘
```

### 4.3 Model Tiering Decision Tree

```
For each page, given template_type:

template_type == "content-text" OR "welcome" OR "summary" ?
  → TIER_SMALL: any available model (phi3:mini, qwen:3b)
  → Fallback: rules-based text generation

template_type == "accordion" OR "tabs" OR "click-reveal" ?
  → TIER_MID: prefer 7B+ model (qwen2.5:7b)
  → Fallback: TIER_SMALL with simplified prompt
  → Fallback: rules-based with content features

template_type == "final-assessment" OR "mcq" ?
  → TIER_LARGE: prefer largest available model
  → Fallback: TIER_MID with few-shot MCQ examples
  → Fallback: rules-based MCQ from key term extraction
```

---

## 5. Low-Level Design — Implementation Contracts

### 5.1 NEW FILE: `app/services/ai/document_splitter.py`

**Purpose:** Replace naive blank-line splitting with semantic boundary detection.

```python
"""Semantic document section splitter — replaces _extract_text() line-based split.

Uses python-docx paragraph styles for DOCX, heading detection for MD/TXT,
and optional LLM pass for semantic boundaries.

LLM-free mode: Uses typographic heuristics (paragraph styles, heading patterns,
numbered lists, section breaks) to detect logical boundaries.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Section:
    """A semantically coherent section of a document."""
    index: int
    heading: str                          # Detected heading or "Untitled Section N"
    content: str                          # Full section text
    content_preview: str                  # First 500 chars
    char_count: int
    # Content features for template selection (filled by FeatureDetector)
    features: Optional[dict] = None

class DocumentSplitter:
    """Splits extracted text into semantic sections.

    Usage:
        splitter = DocumentSplitter(use_llm=False)  # Pure heuristics
        sections = splitter.split(text, filename, detected_format)
        
        splitter = DocumentSplitter(use_llm=True)    # LLM-enhanced
        sections = await splitter.split_async(text, filename, detected_format)
    """

    def __init__(self, use_llm: bool = False, llm_client=None):
        self.use_llm = use_llm
        self.llm_client = llm_client

    # ── Public API ─────────────────────────────────────────────────

    def split(self, text: str, filename: str, fmt: str = "md") -> List[Section]:
        """Split text into sections using heuristics only."""
        if fmt == "docx":
            return self._split_by_styles(text, filename)
        return self._split_by_headings(text, filename)

    async def split_async(self, text: str, filename: str, fmt: str = "md") -> List[Section]:
        """Split text into sections, optionally using LLM for semantic boundaries."""
        sections = self.split(text, filename, fmt)
        if self.use_llm and self.llm_client:
            sections = await self._llm_refine_boundaries(sections)
        return sections

    # ── Heuristic Splitters ────────────────────────────────────────

    def _split_by_styles(self, text: str, filename: str) -> List[Section]:
        """DOCX: detect sections by paragraph styles, large text, numbered headings."""
        lines = text.split("\n")
        sections = []
        current_lines = []
        current_heading = filename

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Heading detection heuristics for DOCX plain text
            is_heading = any([
                len(stripped) < 120 and stripped.isupper(),          # ALL CAPS short line
                re.match(r'^(?:Module|Unit|Lesson|Chapter|Section|Topic|Part)\s+\d+', stripped, re.I),
                re.match(r'^\d+[\.\)]\s+[A-Z]', stripped),           # Numbered heading
                re.match(r'^[A-Z][a-z\s]{10,60}$', stripped),        # Title-case phrase
                stripped.endswith(':') and len(stripped) < 80,       # "Topic:"
            ])

            if is_heading and current_lines:
                sections.append(self._make_section(
                    len(sections), current_heading, current_lines))
                current_heading = stripped
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections.append(self._make_section(
                len(sections), current_heading, current_lines))

        return sections if sections else [self._make_section(0, filename, lines)]

    def _split_by_headings(self, text: str, filename: str) -> List[Section]:
        """MD/TXT: detect sections by markdown headings and blank-line groups."""
        lines = text.split("\n")
        sections = []
        current_lines = []
        current_heading = filename

        for line in lines:
            stripped = line.strip()

            # Markdown heading
            if stripped.startswith("#"):
                if current_lines:
                    sections.append(self._make_section(
                        len(sections), current_heading, current_lines))
                current_heading = stripped.lstrip("#").strip()
                current_lines = []
                continue

            # Blank line = paragraph boundary
            if not stripped:
                if len(current_lines) > 3:  # 3+ consecutive non-blank lines = enough content
                    sections.append(self._make_section(
                        len(sections), current_heading, current_lines))
                    current_heading = filename
                    current_lines = []
                continue

            current_lines.append(line)

        if current_lines:
            sections.append(self._make_section(
                len(sections), current_heading, current_lines))

        return sections if sections else [self._make_section(0, filename, lines)]

    # ── LLM Enhancement ────────────────────────────────────────────

    async def _llm_refine_boundaries(self, sections: List[Section]) -> List[Section]:
        """Use LLM to merge over-split sections or split under-split ones."""
        if len(sections) <= 1:
            return sections

        previews = "\n\n".join(
            f"[{s.index}] {s.heading}\n{s.content_preview}"
            for s in sections
        )

        prompt = (
            "Analyze these document sections. Return a JSON array indicating "
            "which consecutive sections should be MERGED (they form one logical unit). "
            "Format: [[from_idx, to_idx], ...]. Return [] if all sections are fine.\n\n"
            f"{previews}"
        )

        # ... LLM call, parse merge instructions, return refined sections
        return sections  # Simplified for contract — full implementation has LLM call

    # ── Helpers ────────────────────────────────────────────────────

    def _make_section(self, idx: int, heading: str, lines: list) -> Section:
        content = "\n".join(lines)
        return Section(
            index=idx,
            heading=heading,
            content=content,
            content_preview=content[:500],
            char_count=len(content),
        )
```

### 5.2 NEW FILE: `app/services/ai/feature_detector.py`

**Purpose:** Zero-LLM content feature extraction for template suitability scoring.
Purely regex and counting — no external dependencies.

```python
"""Zero-LLM content feature detection for template selection.

All features are computed from plain text using regex and counting —
no model calls, no API dependencies. Runs in < 1ms per section.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class ContentFeatures:
    """Structural and semantic features extracted from a document section."""
    # ── Structural ──
    char_count: int = 0
    line_count: int = 0
    paragraph_count: int = 0
    avg_paragraph_length: float = 0.0

    # ── Heading detection ──
    has_heading: bool = False
    heading_count: int = 0
    bold_text_count: int = 0

    # ── Sub-topic detection ──
    sub_topic_count: int = 0
    sub_topics_independent: bool = False   # Each sub-topic can stand alone
    sub_topics_parallel: bool = False      # Sub-topics are equal alternatives

    # ── Content patterns ──
    has_qa_pattern: bool = False
    has_list: bool = False
    has_callout: bool = False
    has_image_refs: bool = False
    has_table: bool = False
    has_code_block: bool = False

    # ── Semantic signals ──
    has_intro_language: bool = False
    has_summary_language: bool = False
    has_assessment_keywords: bool = False
    has_term_definitions: bool = False
    has_procedure_steps: bool = False
    has_narrative_structure: bool = False

    # ── Position ──
    section_position: float = 0.0
    is_first: bool = False
    is_last: bool = False
    is_before_assessment: bool = False


class FeatureDetector:
    """Extract ContentFeatures from a text section.

    Usage:
        detector = FeatureDetector()
        features = detector.detect(text, section_index=0, total_sections=10)
    """

    # ── Regex patterns (compiled once at class level) ─────────────

    _HEADING_PAT = re.compile(r'^#+\s|^[A-Z][\w\s]{5,50}$')
    _BOLD_PAT = re.compile(r'\*\*(.+?)\*\*')
    _SUBTOPIC_PAT = re.compile(r'^(?:#+|\d+[\.\)]|[A-Z][\w\s]{3,40}:)', re.MULTILINE)
    _QA_PAT = re.compile(r'(?:Q:.*\n.*A:|What\s+is\s+.+\?|How\s+(?:do|does|can|should).+\?)', re.MULTILINE)
    _LIST_PAT = re.compile(r'^[\-\*\•\→]\s|^\d+[\.\)]\s', re.MULTILINE)
    _CALLOUT_PAT = re.compile(r'(?:Note|Tip|Warning|Important|Did you know|Key Takeaway|Remember)', re.IGNORECASE)
    _IMAGE_PAT = re.compile(r'!\[|\[image\]|\[figure\]|\(fig\s|\(see\s(?:fig|figure)', re.IGNORECASE)
    _TABLE_PAT = re.compile(r'\|.+\|.*\n\|[-|]+\|')
    _CODE_PAT = re.compile(r'```|`[^`]+`')
    _INTRO_PAT = re.compile(r'\b(?:welcome|introduction|overview|getting\s+started|about\s+this\s+course)\b', re.IGNORECASE)
    _SUMMARY_PAT = re.compile(r'\b(?:summary|conclusion|key\s+takeaways?|in\s+summary|to\s+summarize|wrap\s+up)\b', re.IGNORECASE)
    _ASSESS_PAT = re.compile(r'\b(?:quiz|test|assessment|check\s+your\s+(?:knowledge|understanding)|evaluation|exam)\b', re.IGNORECASE)
    _TERM_PAT = re.compile(r'\b(\w[\w\s]{2,30})\s*[:\-—]\s*.{10,}')
    _PROCEDURE_PAT = re.compile(r'(?:step\s+\d|first,?\s|next,?\s|then,?\s|finally,?\s|1\.\s.*\n\s*2\.\s)', re.IGNORECASE)

    # ── Public API ─────────────────────────────────────────────────

    def detect(self, text: str, section_index: int = 0,
               total_sections: int = 1) -> ContentFeatures:
        """Extract all features from a text section."""
        lines = text.strip().split("\n")
        non_empty = [l for l in lines if l.strip()]
        para_count = sum(1 for l in non_empty if not l.startswith("#") and len(l.strip()) > 10)

        return ContentFeatures(
            char_count=len(text),
            line_count=len(lines),
            paragraph_count=para_count,
            avg_paragraph_length=sum(len(l.strip()) for l in non_empty) / max(len(non_empty), 1),

            has_heading=bool(self._HEADING_PAT.match(non_empty[0].strip())) if non_empty else False,
            heading_count=len(self._HEADING_PAT.findall(text)),
            bold_text_count=len(self._BOLD_PAT.findall(text)),

            sub_topic_count=len(self._SUBTOPIC_PAT.findall(text)),
            sub_topics_independent=self._check_independent_subtopics(non_empty),
            sub_topics_parallel=self._check_parallel_subtopics(non_empty),

            has_qa_pattern=bool(self._QA_PAT.search(text)),
            has_list=bool(self._LIST_PAT.search(text)),
            has_callout=bool(self._CALLOUT_PAT.search(text)),
            has_image_refs=bool(self._IMAGE_PAT.search(text)),
            has_table=bool(self._TABLE_PAT.search(text)),
            has_code_block=bool(self._CODE_PAT.search(text)),

            has_intro_language=bool(self._INTRO_PAT.search(text)),
            has_summary_language=bool(self._SUMMARY_PAT.search(text)),
            has_assessment_keywords=bool(self._ASSESS_PAT.search(text)),
            has_term_definitions=bool(self._TERM_PAT.search(text)),
            has_procedure_steps=bool(self._PROCEDURE_PAT.search(text)),
            has_narrative_structure=len(text) > 500 and len(non_empty) > 3,

            section_position=section_index / max(total_sections, 1),
            is_first=section_index == 0,
            is_last=section_index == total_sections - 1,
            is_before_assessment=section_index == total_sections - 2,
        )

    # ── Private Helpers ───────────────────────────────────────────

    def _check_independent_subtopics(self, lines: list) -> bool:
        """Check if sub-topics can be read independently (accordion pattern)."""
        sub_headings = [l for l in lines if self._SUBTOPIC_PAT.match(l.strip())]
        return len(sub_headings) >= 3

    def _check_parallel_subtopics(self, lines: list) -> bool:
        """Check if sub-topics are parallel alternatives (tabs pattern)."""
        sub_headings = [l.strip() for l in lines if self._SUBTOPIC_PAT.match(l.strip())]
        if len(sub_headings) < 2:
            return False
        lengths = [len(h) for h in sub_headings]
        avg = sum(lengths) / len(lengths)
        # Parallel if heading lengths are similar (within 30% of average)
        return all(abs(l - avg) / avg < 0.3 for l in lengths)
```

### 5.3 NEW FILE: `app/services/ai/template_selector.py`

**Purpose:** Score template suitability from content features. Zero LLM dependency for
basic scoring; optional LLM refinement for ambiguous cases.

```python
"""Template suitability scoring engine.

Phase 1: Rules-based scoring from ContentFeatures (ZERO LLM).
Phase 2: LLM refinement only for ambiguous cases (score margin < 0.3).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.services.ai.feature_detector import ContentFeatures

# ═══════════════════════════════════════════════════════════════════
# Template Suitability Heuristics
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TemplateScore:
    """Score for a single template type."""
    template_type: str
    score: float           # 0.0 - 1.0
    confidence: float      # 0.0 - 1.0 (how certain the score is)
    method: str            # "heuristic" | "llm"
    reasoning: str         # Human-readable explanation

# Valid template types from template_contracts.py BUSINESS_RULES
VALID_TEMPLATES = [
    "content-text", "tabs", "accordion", "click-reveal", "final-assessment",
    "welcome", "summary", "content-video", "content-media", "mcq",
]

# ── Heuristic Rules ────────────────────────────────────────────────
# Each rule: (condition_fn, template_type, base_score, confidence)

def _rule_single_narrative(f: ContentFeatures) -> Optional[TemplateScore]:
    """Single topic with narrative flow → content-text."""
    if f.has_narrative_structure and f.sub_topic_count < 3 and not f.has_qa_pattern:
        return TemplateScore("content-text", 0.90, 0.85, "heuristic",
                            "Single narrative topic, no sub-topic structure")
    return None

def _rule_accordion(f: ContentFeatures) -> Optional[TemplateScore]:
    """3+ independent sub-topics → accordion."""
    if f.sub_topics_independent and f.sub_topic_count >= 3:
        score = min(0.95, 0.70 + (f.sub_topic_count - 3) * 0.05)
        return TemplateScore("accordion", score, 0.80, "heuristic",
                            f"{f.sub_topic_count} independent sub-topics detected")
    return None

def _rule_tabs(f: ContentFeatures) -> Optional[TemplateScore]:
    """2+ parallel sub-topics or procedure steps → tabs."""
    if f.sub_topics_parallel and f.sub_topic_count >= 2:
        return TemplateScore("tabs", 0.80, 0.75, "heuristic",
                            f"{f.sub_topic_count} parallel sub-topics detected")
    if f.has_procedure_steps:
        return TemplateScore("tabs", 0.75, 0.70, "heuristic",
                            "Procedure/steps pattern detected")
    return None

def _rule_click_reveal(f: ContentFeatures) -> Optional[TemplateScore]:
    """Q&A pattern → click-reveal."""
    if f.has_qa_pattern:
        return TemplateScore("click-reveal", 0.85, 0.85, "heuristic",
                            "Q&A pattern detected")
    return None

def _rule_assessment(f: ContentFeatures) -> Optional[TemplateScore]:
    """Assessment keywords + near end of document → final-assessment."""
    if f.has_assessment_keywords:
        return TemplateScore("final-assessment", 0.90, 0.85, "heuristic",
                            "Assessment keywords detected")
    if f.is_last and (f.has_qa_pattern or f.char_count > 500):
        return TemplateScore("final-assessment", 0.50, 0.40, "heuristic",
                            "Last section — might be assessment")
    return None

def _rule_welcome(f: ContentFeatures) -> Optional[TemplateScore]:
    """First section with intro language → welcome."""
    if f.is_first and f.has_intro_language:
        return TemplateScore("welcome", 0.90, 0.90, "heuristic",
                            "First section with introduction language")
    return None

def _rule_summary(f: ContentFeatures) -> Optional[TemplateScore]:
    """Near end + summary language → summary."""
    if f.has_summary_language:
        return TemplateScore("summary", 0.90, 0.85, "heuristic",
                            "Summary language detected")
    if f.is_last and not f.has_assessment_keywords:
        return TemplateScore("summary", 0.45, 0.35, "heuristic",
                            "Last section without assessment content")
    return None

def _rule_term_definitions(f: ContentFeatures) -> Optional[TemplateScore]:
    """Term: definition patterns → accordion."""
    if f.has_term_definitions and f.sub_topic_count >= 2:
        return TemplateScore("accordion", 0.70, 0.65, "heuristic",
                            f"{f.sub_topic_count} term definitions detected")
    return None

# All rules in evaluation order
ALL_RULES = [
    _rule_welcome,
    _rule_assessment,
    _rule_summary,
    _rule_click_reveal,
    _rule_tabs,
    _rule_accordion,
    _rule_term_definitions,
    _rule_single_narrative,
]

DEFAULT_TEMPLATE = TemplateScore("content-text", 0.40, 0.30, "heuristic",
                                 "Fallback — no strong signal")


class TemplateSelector:
    """Score and select templates for document sections.

    Usage:
        selector = TemplateSelector()
        scores = selector.score_all(features)          # All template scores
        best = selector.select(features)                # Single best template
        best, needs_llm = selector.select_with_confidence(features)  # + refinement flag
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    # ── Public API ─────────────────────────────────────────────────

    def score_all(self, features: ContentFeatures) -> List[TemplateScore]:
        """Score all applicable templates for a section."""
        scores = []
        for rule in ALL_RULES:
            result = rule(features)
            if result is not None:
                scores.append(result)

        scores.sort(key=lambda s: s.score, reverse=True)

        # Always include content-text as minimum viable
        if not any(s.template_type == "content-text" for s in scores):
            scores.append(DEFAULT_TEMPLATE)

        return scores

    def select(self, features: ContentFeatures) -> TemplateScore:
        """Select the best template. No LLM refinement."""
        scores = self.score_all(features)
        return scores[0] if scores else DEFAULT_TEMPLATE

    def select_with_confidence(self, features: ContentFeatures
                               ) -> Tuple[TemplateScore, bool]:
        """Select best template, indicating if LLM refinement is needed.

        Returns:
            (best_template, needs_llm_refinement)
            needs_llm_refinement is True when top 2 scores are within 0.3 margin.
        """
        scores = self.score_all(features)
        if not scores:
            return DEFAULT_TEMPLATE, False

        best = scores[0]
        second = scores[1] if len(scores) > 1 else None

        needs_llm = (
            second is not None
            and (best.score - second.score) < 0.3
            and best.confidence < 0.80
        )

        return best, needs_llm

    # ── LLM Refinement ─────────────────────────────────────────────

    async def llm_refine(self, features: ContentFeatures,
                         candidates: List[TemplateScore],
                         section_text: str) -> TemplateScore:
        """Use LLM to choose between ambiguous template candidates.

        Only called when select_with_confidence() returns needs_llm=True.
        Works with any model size — small models do simple choice,
        large models can override with creative selections.
        """
        if not self.llm_client:
            return candidates[0]  # No LLM available, return best heuristic

        prompt = (
            f"Content features: {features.__dict__}\n\n"
            f"Section text (first 500 chars): {section_text[:500]}\n\n"
            f"Top template candidates:\n"
            + "\n".join(f"- {c.template_type} (score {c.score:.2f}): {c.reasoning}"
                        for c in candidates[:3])
            + "\n\nReturn JSON: {\"template_type\": \"...\", \"reasoning\": \"...\"}"
        )

        # ... LLM call ...
        return candidates[0]  # Simplified — full impl has LLM call + JSON parse
```

### 5.4 REFACTOR: `app/services/ai/course_generator.py`

**Changes to `_generate_page_content()` (line 652):**

Replace monolithic mock generator with template-specific generators:

```python
# ── NEW: Template-specific content generators ──────────────────────

def _generate_text_content(page: dict, source: str, features: ContentFeatures
                           ) -> List[dict]:
    """Generate content-text component with optional callout + key takeaways."""
    components = []
    title = page.get("title", "Untitled")

    # Main content component
    components.append({
        "component_type": "content-text",
        "order_index": 0,
        "data": {
            "content": (
                f"<h2>{title}</h2>\n"
                f"<p>{source[:500] if source else 'Content for ' + title.lower()}</p>"
            ),
        },
    })

    # Callout box if content has callout pattern
    if features and features.has_callout:
        components.append({
            "component_type": "content-text",
            "order_index": 1,
            "data": {
                "content": (
                    f"<div class=\"callout-box\">\n"
                    f"  <h3>Key Takeaway</h3>\n"
                    f"  <p>The most important concept from this section.</p>\n"
                    f"</div>"
                ),
            },
        })

    # Key takeaways list if section has multiple points
    if features and features.has_list:
        components.append({
            "component_type": "content-text",
            "order_index": len(components),
            "data": {
                "content": (
                    f"<h3>Key Points</h3>\n<ul>\n"
                    + "\n".join(f"  <li>Point from: {title.lower()}</li>"
                                for _ in range(min(3, features.sub_topic_count or 1)))
                    + "\n</ul>"
                ),
            },
        })

    return components


def _generate_accordion_content(page: dict, source: str, features: ContentFeatures
                                ) -> List[dict]:
    """Generate accordion component with detected sub-topics as panels."""
    items = []
    sub_count = features.sub_topic_count if features else 0

    if sub_count >= 3:
        for i in range(min(sub_count, 6)):
            items.append({
                "title": f"Topic {i+1}: {page.get('title', 'Detail')}",
                "content": f"Detailed explanation of topic {i+1} from source material.",
            })
    else:
        items = [
            {"title": "Overview", "content": f"Introduction to {page.get('title', 'this topic')}."},
            {"title": "Key Details", "content": source[:300] if source else "Detailed information."},
            {"title": "Summary", "content": f"Key takeaways from this section."},
        ]

    return [{
        "component_type": "accordion",
        "order_index": 0,
        "data": {"items": items},
    }]


def _generate_tabs_content(page: dict, source: str, features: ContentFeatures
                           ) -> List[dict]:
    """Generate tabs component with parallel sub-topics as tabs."""
    sub_count = features.sub_topic_count if features else 0

    if features and features.has_procedure_steps:
        tabs = [
            {"title": "Preparation", "content": "What you need before starting."},
            {"title": "Step-by-Step", "content": source[:400] if source else "Follow these steps."},
            {"title": "Result", "content": "What you should see after completing the steps."},
        ]
    elif sub_count >= 2:
        tabs = [
            {"title": f"Aspect {i+1}", "content": f"Content for aspect {i+1}."}
            for i in range(min(sub_count, 5))
        ]
    else:
        tabs = [
            {"title": "Overview", "content": source[:200] if source else "Overview."},
            {"title": "Details", "content": "More detailed information."},
        ]

    return [{
        "component_type": "tabs",
        "order_index": 0,
        "data": {"tabs": tabs},
    }]


def _generate_assessment_content(page: dict, source: str, features: ContentFeatures,
                                 all_page_titles: List[str]) -> List[dict]:
    """Generate assessment with rules-based MCQs when LLM unavailable.

    Args:
        all_page_titles: Titles of all pages in the course — used to generate
                        topic-specific questions when LLM not available.
    """
    # Always generate at least 3 questions, even without LLM
    questions = []
    for i, title in enumerate(all_page_titles[:5]):
        questions.append({
            "id": f"q-{i+1}",
            "type": "mcq",
            "question": f"Which of the following best describes the main concept of {title}?",
            "options": [
                {"id": f"q{i+1}-a", "text": f"The correct understanding of {title.lower()}", "isCorrect": True},
                {"id": f"q{i+1}-b", "text": f"A partial understanding that misses key details", "isCorrect": False},
                {"id": f"q{i+1}-c", "text": f"A common misconception about this topic", "isCorrect": False},
                {"id": f"q{i+1}-d", "text": f"An unrelated concept from a different domain", "isCorrect": False},
            ],
            "feedback": f"Review the section on {title} for the correct answer.",
        })

    return [{
        "component_type": "final-assessment",
        "order_index": 0,
        "data": {
            "passing_score": 80,
            "questions": questions,
        },
    }]
```

### 5.5 REFACTOR: `app/routers/ai_ingestion.py` — `_call_llm_for_breakdown()`

**Changes to line 576 — model selection:**

```python
# BEFORE (line 576):
"model": "phi3:mini",

# AFTER:
"model": _resolve_breakdown_model(),
```

Where `_resolve_breakdown_model()` is:

```python
def _resolve_breakdown_model() -> str:
    """Resolve the best available model for template classification.

    Decision tree:
    1. Check AI config for explicitly configured planner model
    2. Fall back to largest available Ollama model
    3. Default to "phi3:mini" if nothing else is available
    """
    cfg = get_ai_config()

    # Check configured planner model
    if cfg.anthropic_api_key:
        return cfg.planner_model or "claude-haiku-4-5"

    # Check available Ollama models via MCP gateway health
    try:
        import httpx
        # ... check available models via Ollama API
        # Prefer: qwen2.5:7b > phi3:mini > any available
    except Exception:
        pass

    return "qwen2.5:7b"  # Better default than phi3:mini
```

### 5.6 REFACTOR: `app/services/ai/ingestion_service.py` — `_extract_text()`

**Changes to line 180 — delegate to DocumentSplitter:**

```python
# BEFORE:
extracted, source_meta = self._extract_text(content, filename, detected)

# AFTER:
from app.services.ai.document_splitter import DocumentSplitter
text = content.decode("utf-8", errors="replace")
splitter = DocumentSplitter(use_llm=False)
sections = splitter.split(text, filename, detected)
extracted = [
    {
        "index": s.index,
        "heading": s.heading,
        "content_preview": s.content_preview,
        "char_count": s.char_count,
    }
    for s in sections
]
source_meta = {
    "page_count": len(sections),
    "total_chars": sum(s.char_count for s in sections),
    "language": "en",
    "title": filename,
}
```

---

## 6. Database / Configuration / API Changes

### 6.1 Database: No schema changes required

All new code operates on existing tables:
- `ai_ingestion_jobs.extracted_sections` (JSON) — section data enriched with features
- `ai_ingestion_jobs.source_metadata` (JSON) — generation metadata + fingerprint
- `pages` + `components` — already support multi-component via FK

### 6.2 Configuration: New env vars

```bash
# .env additions (all optional — heuristics work without them)
AI_TEMPLATE_SELECTOR_LLM_ENABLED=false    # Enable LLM refinement (default: false)
AI_TEMPLATE_SELECTOR_MODEL=qwen2.5:7b     # Model for ambiguous template selection
AI_SEMANTIC_SPLITTER_ENABLED=false        # Enable LLM semantic boundaries (default: false)
AI_RULES_BASED_MCQ_MIN_QUESTIONS=3        # Minimum MCQs from rules-based generator
AI_COMPONENT_HIERARCHY_ENABLED=true       # Enable multi-component detection (default: true)
```

### 6.3 API Contracts: No breaking changes

All existing API paths, request/response schemas unchanged. New behavior is
internal to the pipeline — same input, better output.

---

## 7. Implementation Sequence with Dependency Graph

```
Phase 1: Zero-LLM Foundation (independent of all other changes)
│
├── [1A] document_splitter.py          ← No dependencies
│   └── Depends on: re, dataclasses (stdlib only)
│   └── Tests: 5 cases (DOCX styles, MD headings, flat text, empty, single-line)
│
├── [1B] feature_detector.py           ← No dependencies
│   └── Depends on: re, dataclasses (stdlib only)
│   └── Tests: 10 cases (each feature pattern, edge cases)
│
├── [1C] template_selector.py          ← Depends on: [1B]
│   └── Depends on: feature_detector.ContentFeatures
│   └── Tests: 5 cases (each template selection, ambiguous case, fallback)
│
└── [1D] Integrate [1A] into ingestion  ← Depends on: [1A]
    └── Depends on: document_splitter, ingestion_service
    └── Tests: 2 integration cases (DOCX upload, MD upload)

Phase 2: Content Generation Enhancement (depends on Phase 1)
│
├── [2A] Refactor _generate_page_content()  ← Depends on: [1B]
│   └── Depends on: feature_detector, template_contracts
│   └── Tests: 5 template-specific generation cases
│
├── [2B] Rules-based MCQ generator     ← Depends on: [2A]
│   └── Depends on: course_generator
│   └── Tests: 3 cases (3, 5, 10 questions)
│
└── [2C] Integrate [1C] into propose-breakdown  ← Depends on: [1C], [2A]
    └── Depends on: template_selector, ai_ingestion
    └── Tests: 2 integration cases

Phase 3: LLM Enhancement (optional, depends on Phase 1+2)
│
├── [3A] Model tiering in generate-course    ← Depends on: [2A]
├── [3B] LLM refinement for ambiguous templates ← Depends on: [1C]
├── [3C] LLM semantic boundaries             ← Depends on: [1A]
└── [3D] Template-specific ContentGeneratorAgents ← Depends on: [2A]
```

---

## 8. Test Plan

### 8.1 Unit Tests

| Test ID | Component | Input | Expected Output |
|---|---|---|---|
| UT-SPLIT-01 | DocumentSplitter | DOCX text with ALL CAPS headings | 6 sections with detected headings |
| UT-SPLIT-02 | DocumentSplitter | MD text with # headings | 4 sections |
| UT-SPLIT-03 | DocumentSplitter | Flat text, no structure | 1 section (filename as heading) |
| UT-SPLIT-04 | DocumentSplitter | Empty text | 1 section (empty content) |
| UT-FEAT-01 | FeatureDetector | "Welcome to... overview... getting started" | has_intro_language=True, is_first=True |
| UT-FEAT-02 | FeatureDetector | "Q: What is X? A: X is..." | has_qa_pattern=True |
| UT-FEAT-03 | FeatureDetector | "Step 1: ... Step 2: ... Step 3: ..." | has_procedure_steps=True, sub_topic_count=3 |
| UT-FEAT-04 | FeatureDetector | "quiz... assessment... test your knowledge" | has_assessment_keywords=True |
| UT-FEAT-05 | FeatureDetector | "Note: ... Important: ... Key Takeaway:" | has_callout=True |
| UT-SEL-01 | TemplateSelector | Features with has_intro_language + is_first | TemplateScore("welcome", >=0.85) |
| UT-SEL-02 | TemplateSelector | Features with sub_topic_count=5, independent | TemplateScore("accordion", >=0.70) |
| UT-SEL-03 | TemplateSelector | Features with has_qa_pattern | TemplateScore("click-reveal", >=0.80) |
| UT-SEL-04 | TemplateSelector | Features with has_assessment_keywords | TemplateScore("final-assessment", >=0.85) |
| UT-SEL-05 | TemplateSelector | Features with no strong signals | TemplateScore("content-text"), needs_llm=True |
| UT-GEN-01 | _generate_text_content | Features with has_callout=True | 2 components (main + callout) |
| UT-GEN-02 | _generate_accordion_content | Features with sub_topic_count=4 | 1 accordion component with 4 items |
| UT-GEN-03 | _generate_tabs_content | Features with has_procedure_steps=True | 1 tabs component with 3 tabs |
| UT-GEN-04 | _generate_assessment_content | 5 page titles | 5 MCQ questions, passing_score=80 |

### 8.2 Integration Tests

| Test ID | Flow | Verification |
|---|---|---|
| IT-01 | Upload SB2 DOCX → check section extraction | ≥ 6 distinct section previews |
| IT-02 | Propose breakdown → check template distribution | ≥ 2 template types used (not all content-text) |
| IT-03 | Generate course → check assessment | 0 mock fallbacks, ≥ 3 MCQs |
| IT-04 | Generate course → check component hierarchy | ≥ 2 pages with 2+ components |
| IT-05 | Full pipeline → export SCORM | Valid SCORM ZIP with correct page count |

---

## 9. Decision Dependencies & Risk Register

### 9.1 Decisions for Reviewer

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Phase 1 LLM dependency: zero vs optional | A) Zero LLM (pure heuristics) B) Optional LLM enhancement | **A** — ship heuristics first, add LLM later |
| D2 | Template selector: replace vs augment existing | A) Replace _llm_propose_breakdown entirely B) Add heuristics as pre-filter, keep LLM as refinement | **B** — lower risk, preserves existing LLM path |
| D3 | Model for template classification | A) Keep phi3:mini B) Upgrade to qwen2.5:7b C) Config-driven | **C** — config-driven with sensible default (qwen2.5:7b) |
| D4 | Assessment: rules-based vs LLM | A) Pure rules-based (no LLM) B) LLM with rules fallback | **B** — try LLM first, rules as safety net |

### 9.2 Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Heuristics misclassify edge cases | Medium | Low | LLM refinement path for ambiguous cases (Phase 2) |
| Rules-based MCQs are too generic | High | Medium | Explicit interim quality bar documented (R5); Phase 2 LLM MCQs are the actual fix |
| Multi-component pages break SCORM export | Low | High | Test export for each template type before shipping |
| More components = slower page load | Low | Low | 2-3 components per page, not 10+ |
| Heuristics overfit to SB2 sample | Medium | High | Multi-document validation corpus (R2) — 10 diverse docs, 6/10 must show diversity |
| Non-English content silently degrades | Medium | Medium | Explicitly documented limitation (R3); skip heuristics when lang≠en; Phase 3 adds i18n keyword sets |
| Feature flag accidentally ships untested | Low | Medium | `AI_COMPONENT_HIERARCHY_ENABLED=false` by default (R8); canary rollout plan documented |
| Template entropy alert not configured | Medium | Medium | Quality metrics dashboard as definition-of-done (R6); alert if entropy < 0.3 for 1hr |

---

## 10. Verification Checklist

- [ ] `PYTHONPATH=. python tests/run_batch6_features_tests.py` — all pass (existing + new)
- [ ] Upload SB2 DOCX → `extracted_sections` shows distinct previews per section
- [ ] `propose-breakdown` → template distribution shows ≥ 2 template types
- [ ] `generate-course` → `final-assessment` page has ≥ 3 topic-specific MCQs
- [ ] `generate-course` → ≥ 2 pages have 2+ components each
- [ ] `apply` → page count correct, no duplicates
- [ ] `export/scorm/{courseId}` → valid SCORM ZIP
- [ ] Upload flat text file → still works (no regression)
- [ ] Upload PDF → still works (no regression)
- [ ] Empty document → graceful handling

---

## 11. Reviewer Feedback Addendum — Architectural Review Response

> **Reviewer:** Agentic AI Architect / TPO  
> **Verdict:** Approve architecture direction — refinements needed, not rejection.  
> **Date:** 2026-07-05

### R1 (Blocker): DOCX Splitter Must Use Real Paragraph Style Metadata

**Reviewer finding:** `DocumentSplitter._split_by_styles` receives flattened plain text and
reconstructs structure via regex — it never touches `python-docx`'s `Paragraph.style.name`.
This is a better heuristic on degraded input, not a fix for the degradation itself.

**Root cause:** `document_extractor.py:98-100` discards `para.style.name` during extraction:
```python
# CURRENT (loses structural info):
for para in doc.paragraphs:
    if para.text.strip():
        text_parts.append(para.text)  # ← style.name discarded
```

**Fix:** Change `DocumentExtractor._extract_docx()` to preserve structured paragraph data:

```python
# FIXED: document_extractor.py — _extract_docx()
def _extract_docx(self, file_path: str) -> dict:
    """Extract structured paragraph data from DOCX.

    Returns dict with:
        raw_text: plain text (backward-compatible)
        paragraphs: [{style_name, text, is_heading}, ...]  ← NEW structured output
    """
    doc = docx.Document(file_path)
    paragraphs = []
    text_parts = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = para.style.name if para.style else "Normal"
        is_heading = style_name.startswith("Heading") or style_name.startswith("heading")

        paragraphs.append({
            "style_name": style_name,
            "text": text,
            "is_heading": is_heading,
            "heading_level": (
                int(style_name.split()[-1]) if is_heading and style_name.split()[-1].isdigit()
                else (1 if is_heading else 0)
            ),
        })
        text_parts.append(text)
        if sum(len(t) for t in text_parts) > self.MAX_CHARS:
            break

    return {
        "raw_text": "\n".join(text_parts)[:self.MAX_CHARS],
        "paragraphs": paragraphs,
    }
```

**Corresponding `DocumentSplitter` change — `_split_by_styles()` now consumes structured data:**

```python
# FIXED: document_splitter.py — _split_by_styles()
def _split_by_structured_paragraphs(self, paragraphs: list, filename: str) -> List[Section]:
    """Primary boundary detector: uses real paragraph styles from python-docx."""
    sections = []
    current_lines = []
    current_heading = filename

    for para in paragraphs:
        text = para["text"]

        # REAL heading detection from style metadata
        if para["is_heading"]:
            if current_lines:
                sections.append(self._make_section(
                    len(sections), current_heading, current_lines))
            current_heading = text  # Use heading text directly
            current_lines = []
            continue

        current_lines.append(text)

    if current_lines:
        sections.append(self._make_section(
            len(sections), current_heading, current_lines))

    # Fallback: if no heading styles found, try text heuristics
    if len(sections) <= 1:
        return self._split_by_heading_heuristics(
            "\n".join(p["text"] for p in paragraphs), filename)

    return sections
```

**Ingestion service integration:**

```python
# ingestion_service.py:create_job() — updated flow
if detected in ("pdf", "docx"):
    if detected == "docx":
        structured = extractor.extract_structured(tmp_path)  # NEW method
        raw_text = structured["raw_text"]
        # Pass structured paragraphs to splitter
        splitter = DocumentSplitter()
        sections = splitter.split_structured(structured["paragraphs"], filename)
    else:
        # PDF: existing flow (pdfplumber doesn't expose styles)
        raw_text = extractor.extract(tmp_path, mime)
        sections = splitter.split(raw_text, filename, "txt")

    extracted = [s.to_dict() for s in sections]
```

**Impact on existing code:** `_extract_docx()` return type changes from `str` to `dict`.
Callers in `create_job()` need to handle the new return shape. `_extract_pdf()` unchanged.

**Verification:** Open SB2 docx → `paragraphs[0].style_name` should show "Heading 1"
or "Title" (not "Normal"). Each detected heading = a section boundary.

### R2: Multi-Document Validation Required

**Add to §10 before shipping:**

| Document | Type | Author | Expected Sections | Expected Templates |
|---|---|---|---|---|
| SB2-Cybersecurity | PPT→DOCX | Corporate trainer | 6-10 | content-text + accordion + tabs + assessment |
| Policy manual | Word DOCX | HR dept | 8-15 | content-text + accordion |
| Technical guide | Word DOCX | Engineering | 10-20 | content-text + tabs + code blocks |
| Training workbook | Word DOCX | L&D | 5-12 | content-text + click-reveal + assessment |
| Plain text notes | TXT | Individual | 3-8 | content-text only |
| Academic paper | PDF | Researcher | 8-20 | content-text + summary |
| Sales playbook | PPT→PDF | Sales ops | 5-15 | content-text + tabs |
| Compliance checklist | Word DOCX | Legal | 6-12 | content-text + accordion |
| Multi-language (ES) | Word DOCX | LATAM trainer | 5-10 | content-text (ES keywords) |
| Empty/single-page | TXT | Any | 1 | content-text |

**Acceptance criteria:** Template diversity ≥ 2 types for at least 6/10 documents.
No document produces 100% content-text (except single-page/empty).

### R3: English-Only Limitation — Explicitly Documented

Added to risk register:

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Non-English content degrades to content-text | Medium (for non-English users) | Medium | Phase 1 heuristics are English-only by design. Non-English docs route through existing LLM path as fallback. Phase 3 adds i18n keyword sets (ES, FR, DE, JP, ZH). Documented in release notes. |

**Detection:** `FeatureDetector` now sets `detected_language = "en"` (explicit, not assumed).
When `detected_language != "en"`, skip heuristics and use LLM refinement path directly.

### R4: Rule Conflict Resolution — Now Fully Specified

Added to `TemplateSelector.score_all()`:

```python
def _arbitrate(self, scores: List[TemplateScore]) -> List[TemplateScore]:
    """Resolve conflicting template scores.

    Rules:
    1. "welcome" beats all others when is_first=True AND score >= 0.80
    2. "final-assessment" beats all others when is_last=True AND score >= 0.70
    3. "summary" beats "content-text" when is_last=True
    4. Among accordion/tabs/click-reveal at similar scores (±0.15):
       prefer accordion > tabs > click-reveal (accessibility hierarchy)
    5. "content-text" is always the fallback when no rule fires above 0.50
    6. When top 2 scores are within 0.30 margin → flag for LLM refinement
    """
```

### R5: MCQ Quality Bar — Explicitly Tiered

Added to §5.4:

| Tier | Method | Questions | Quality | When |
|---|---|---|---|---|
| **Interim (Phase 1)** | Rules-based templates | ≥ 3 | Formulaic but topic-labeled | LLM unavailable |
| **Target (Phase 2)** | LLM with few-shot examples | ≥ 5 | Topic-specific stems + plausible distractors | qwen2.5:7b+ |
| **Premium (Phase 3)** | Dedicated AssessmentAgent | ≥ 10 | Domain-adaptive difficulty, feedback per option | Claude/OpenAI |

Documented in §1.2 as: "Phase 1 delivers functional assessments (≥3 questions, topic-labeled). Full-quality MCQs require Phase 2 LLM generation. This is an explicit interim quality bar."

### R6: Production Observability Plan

Added to §10:

```python
# NEW: app/services/ai/quality_metrics.py

@dataclass
class GenerationQualityMetrics:
    """Per-generation quality telemetry — emitted as OTEL metrics + structured logs."""
    job_id: str
    template_distribution: Dict[str, int]     # {"content-text": 7, "accordion": 2, ...}
    template_entropy: float                   # Shannon entropy of distribution (>0 = diverse)
    mock_fallback_count: int                  # Pages using mock fallback
    assessment_question_count: int            # MCQs generated
    multi_component_page_count: int           # Pages with ≥2 components
    section_extraction_quality: float         # Distinct previews / total sections
    llm_model_used: str                       # Actual model used
    provider: str                             # Actual provider
    total_duration_ms: int                    # Pipeline wall-clock

    # Alert thresholds (config-driven)
    TEMPLATE_ENTROPY_ALERT = 0.3              # Below this → mostly one template type
    MOCK_FALLBACK_ALERT_RATE = 0.3            # Above 30% → check LLM health
    ASSESSMENT_MIN_QUESTIONS = 3              # Below this → assessment degraded
```

**Dashboard queries (Grafana / SQL):**
```sql
-- Template entropy trend (alert if trending toward 0 = all content-text)
SELECT date_trunc('hour', created_at), AVG(template_entropy)
FROM generation_quality_metrics GROUP BY 1 ORDER BY 1;

-- Mock fallback rate (alert if >30%)
SELECT date_trunc('hour', created_at),
       SUM(mock_fallback_count)::float / NULLIF(SUM(total_pages), 0) AS rate
FROM generation_quality_metrics GROUP BY 1;

-- Assessment quality (alert if avg MCQs < 3)
SELECT date_trunc('hour', created_at), AVG(assessment_question_count)
FROM generation_quality_metrics GROUP BY 1;
```

### R7: Effort Estimates

Added to §7:

| Work Item | Effort (days) | Owner Skill | Dependencies |
|---|---|---|---|
| [1A] DocumentSplitter | 1.5d | Mid-level BE | None |
| [1A-fix] DOCX structured extraction (R1) | 1d | Mid-level BE | None |
| [1B] FeatureDetector | 2d | Mid-level BE | None |
| [1C] TemplateSelector | 2d | Senior BE | [1B] |
| [1D] Integrate into ingestion | 1d | Mid-level BE | [1A], [1A-fix] |
| [2A] Refactor _generate_page_content | 2d | Senior BE | [1B] |
| [2B] Rules-based MCQ generator | 1.5d | Mid-level BE | [2A] |
| [2C] Integrate into propose-breakdown | 1d | Senior BE | [1C], [2A] |
| [3A] Model tiering router | 1.5d | Senior BE | [2A] |
| [3B] LLM refinement (ambiguous templates) | 1d | Senior BE | [1C] |
| [3C] LLM semantic boundaries | 1d | Senior BE | [1A] |
| [3D] Template-specific agents | 3d | Senior BE | [2A] |
| **Phase 1 total** | **10.5d** | | |
| **Phase 2 total** | **5.5d** | | |
| **Phase 3 total** | **6.5d** | | |
| **Grand total** | **22.5d** (~4.5 weeks) | | |

### R8: Feature Flag Defaults — Revised

Changed defaults in §6.2:

```bash
# REVISED DEFAULTS — safe initial rollout
AI_TEMPLATE_SELECTOR_LLM_ENABLED=false       # Keep false (heuristics first)
AI_TEMPLATE_SELECTOR_MODEL=qwen2.5:7b        # Optional, only when LLM enabled
AI_SEMANTIC_SPLITTER_ENABLED=false           # Keep false (style metadata is primary)
AI_RULES_BASED_MCQ_MIN_QUESTIONS=3           # OK — formulaic but functional
AI_COMPONENT_HIERARCHY_ENABLED=false         # ← CHANGED from true to false
                                              # Enable after multi-doc validation (R2)

# Rollout plan:
# Week 1: AI_COMPONENT_HIERARCHY_ENABLED=false (heuristics collect metrics only)
# Week 2: AI_COMPONENT_HIERARCHY_ENABLED=true for 20% of courses (canary)
# Week 3: AI_COMPONENT_HIERARCHY_ENABLED=true for 100% (if metrics stable)
```

### Additional Fixes Noted by Reviewer

**G4 (provider mislabeling):** The `"provider": "anthropic"` bug traced to
`course_generator.py:577`:
```python
provider = LLMProvider.ANTHROPIC if cfg.anthropic_api_key else LLMProvider.MOCK
```
When `ANTHROPIC_BASE_URL` points to DeepSeek/Ollama with an API key set, the provider
is still labeled "anthropic". Fix: detect actual provider from config:
```python
provider = cfg.generation_provider or (
    LLMProvider.ANTHROPIC if cfg.anthropic_api_key else LLMProvider.MOCK
)
```
Added to Phase 1 as a 0.5d fix alongside [1A].

**P6 (model escalation on failure):** Moved from Phase 3 (optional) to Phase 2:
```python
MODEL_ESCALATION_CHAIN = ["qwen2.5:7b", "phi3:mini", "mock"]
# Try each model in chain; first success wins; mock is last resort
```
Added to [2A] as part of the content generation refactor.

---

## 12. Revised Implementation Priority

| Priority | Phase | Item | Effort |
|---|---|---|---|
| **P0** | Phase 1 | [1A-fix] DOCX structured extraction (R1) | 1d |
| **P0** | Phase 1 | [1A] DocumentSplitter with style metadata | 1.5d |
| **P0** | Phase 1 | [1B] FeatureDetector | 2d |
| **P0** | Phase 1 | [1C] TemplateSelector with rule arbitration (R4) | 2d |
| **P0** | Phase 1 | [G4 fix] Provider label correction | 0.5d |
| **P0** | Phase 1 | [1D] Integration + quality metrics (R6) | 1.5d |
| **P1** | Phase 2 | [2A] Refactor generation + model escalation (P6) | 2.5d |
| **P1** | Phase 2 | [2B] Rules-based MCQ (R5 interim bar) | 1.5d |
| **P1** | Phase 2 | [2C] Integrate template selector | 1d |
| **P2** | Phase 3 | [3A] Model tiering router | 1.5d |
| **P2** | Phase 3 | [3B] LLM refinement for ambiguous templates | 1d |
| **P2** | Phase 3 | [3D] Template-specific ContentGeneratorAgents | 3d |
| **P3** | Phase 3 | [3C] LLM semantic boundaries (i18n enablement) | 1d |
| **P3** | Backlog | i18n keyword sets (ES, FR, DE, JP, ZH) | 3d |
