# Technical Requirements Document: Course Generation Quality RCA & Fix

> **Date:** 2026-07-05  
> **Status:** Production Blocker  
> **Author:** Agentic AI Engineering  
> **Scope:** End-to-end course generation pipeline quality

---

## Executive Summary

The course generation pipeline produces sub-optimal output: template selection defaults to
`content-text` for all pages, component hierarchies are flattened, assessment questions use
mock fallback, and content structure lacks interactive elements. This TRD provides a
grassroots-level RCA of each pipeline stage and proposes generically architected solutions
that work from small-param LLMs (phi3:mini / qwen2.5:7b) to large frontier models.

---

## 1. Current Pipeline Architecture

```
Upload DOCX → Extract Text → Split Sections → Propose Breakdown → Generate Content → Apply Pages
   [1]           [2]             [3]               [4]                 [5]              [6]
```

| Stage | File | Function | LLM |
|---|---|---|---|
| 1. Upload | `ai_ingestion.py:21` | `upload_document()` | None |
| 2. Extract | `document_extractor.py:32` | `DocumentExtractor.extract()` | None |
| 3. Split | `ingestion_service.py:180` | `_extract_text()` | None |
| 4. Propose | `ai_ingestion.py:488` | `_llm_propose_breakdown()` | `phi3:mini` (2GB) |
| 5. Generate | `course_generator.py:558` | `_generate_pages_with_llm()` | `qwen2.5:7b` (4.3GB) |
| 6. Apply | `course_generator.py:319` | `apply_generated_course()` | None |

---

## 2. RCA: Stage-by-Stage Analysis

### Stage 2-3: Document Extraction & Section Splitting

**Current behavior:**
```python
# ingestion_service.py:180 _extract_text()
# Splits text by blank lines or markdown headings
# DOCX text is flat stream → all sections get same heading
```

**Root problem:** `DocumentExtractor.extract()` for DOCX calls `python-docx` to extract
paragraph text, then joins paragraphs with `\n`. The paragraph structure is preserved, but
`_extract_text()` splits naively by blank lines. PowerPoint-to-DOCX conversions produce
text without blank-line separators between slides → all sections look identical.

**Evidence from SB2 docx:**
- Sections 2-5 all show identical `content_preview` starting with "Welcome to Cybersecurity Awareness\nExplore the structure..."
- Section 1 shows "Tab 1\n—Page -1 Welcome page Text Content—" (garbled)
- The total `char_count` per section is 0 (extraction failure)

**Impact:** Poor section quality → LLM receives garbage input → defaults to safest template (`content-text`) for every page.

### Stage 4: Template Selection (propose-breakdown)

**Current behavior:**
```python
# ai_ingestion.py:570-583 _call_llm_for_breakdown()
# Uses phi3:mini (2GB) via MCP Gateway at :8004
# Prompt includes template schemas + RAG context + section text
# Model returns JSON array of {title, template_type, rationale, source_section_ids, order}
```

**Root problems:**

| # | Problem | Impact |
|---|---|---|
| 4.1 | `phi3:mini` (2B params) is underpowered for template classification | Defaults to `content-text` — safest when uncertain |
| 4.2 | Prompt sends garbled section previews (from Stage 3) | LLM can't determine content type → defaults |
| 4.3 | No template suitability heuristics fallback | Pure LLM decision, no rules-based validation |
| 4.4 | No multi-component detection | Never proposes accordion/tabs even when sections have sub-topics |
| 4.5 | Single LLM call for all decisions | No iterative refinement or self-review |

**Evidence from PRD04 generation:**
- 9/10 pages = `content-text` (identical template)
- 0 pages = `accordion` or `tabs` (interactive templates unused)
- Page 2 "Understanding Cyber Threats" has 5 sub-topics → should be `accordion`
- Page 3 "Protecting Accounts" has 4 sub-topics → should be `tabs`

### Stage 5: Content Generation (generate-course)

**Current behavior:**
```python
# course_generator.py:558 _generate_pages_with_llm()
# Uses ContentGeneratorAgent + StreamManager for parallel LLM generation
# Falls back to _generate_page_content() (mock) on failure
```

**Root problems:**

| # | Problem | Impact |
|---|---|---|
| 5.1 | `final-assessment` template always hits mock fallback | Generic MCQ, no topic-specific questions |
| 5.2 | Single-pass generation — no content review/improvement loop | Low-quality content accepted as-is |
| 5.3 | No template-specific generation prompts | Same prompt for accordion/tabs/content-text |
| 5.4 | Component count hardcoded to 1 in mock generator | No multi-component pages |
| 5.5 | LLM model selection not tiered by template complexity | Simple text page uses same LLM as complex MCQ |

**Evidence from PRD04 generation:**
- Page 10 (Final Assessment): `"fallback": true, "method": "inline_mock"` — 1 generic MCQ
- Pages 8-9 (Workspace, Networks): `"fallback": true` — mock content instead of LLM-generated
- `"provider": "anthropic"` but actual provider is Ollama — provider routing confusion

### Stage 6: Apply (persist pages)

**Current behavior:** Correctly persists generated pages → no quality issue here.
Multi-component generation data from Stage 5 is correctly stored.

---

## 3. Proposed Solutions — Tiered by LLM Capability

### Architecture Principle

```
                    ┌─────────────────────────────┐
                    │    Template Suitability      │
                    │    Heuristics Engine         │
                    │    (Rules + Small LLM)       │
                    └──────────┬──────────────────┘
                               │ assigns template per page
                               ▼
              ┌────────────────────────────────────┐
              │  Content Generation Router          │
              │  (Model tiering by template type)   │
              └───┬────────────┬────────────┬──────┘
                  │            │            │
        ┌─────────▼──┐  ┌─────▼─────┐  ┌──▼──────────┐
        │ Small LLM   │  │ Mid LLM   │  │ Large LLM    │
        │ (phi3:mini) │  │ (qwen:7b) │  │ (claude/etc) │
        │ plain text  │  │ accordion │  │ assessment   │
        │             │  │ tabs      │  │ multi-comp   │
        └─────────────┘  └───────────┘  └──────────────┘
```

### Solution A: Section Extraction — Semantic Boundary Detection

**Current:** Naive blank-line splitting.  
**Proposed:** Two-pass extraction with semantic boundary detection.

```
Pass 1: Extract raw text (existing DocumentExtractor)
Pass 2: Send text to small LLM for semantic sectioning:
  "Identify logical sections in this document. Return section boundaries
   with headings and content summaries. Group related paragraphs."
```

**Fallback (no LLM):** Use typographic heuristics:
- Bold/large text → heading
- Numbered lists → section boundaries
- Slide/page breaks → section boundaries (from python-docx paragraph styles)
- Consecutive short lines → bullet points

**Recommendation:** Implement typographic heuristics first (works without LLM), then
add LLM pass for quality improvement on mid+ tier models.

### Solution B: Template Selection — Multi-Pass with Heuristics

**Current:** Single phi3:mini call for all decisions.  
**Proposed:** Three-pass template selection:

```
Pass 1: Content Classification (rules-based, no LLM)
  - Count sub-topics (headings, numbered items, section breaks)
  - Detect Q&A patterns (question marks, "Q:" prefixes)
  - Detect assessment patterns ("quiz", "test", "assessment", "check your knowledge")
  - Measure content density (char count, paragraph count)
  → Output: content_features dict per section

Pass 2: Template Scoring (rules-based, no LLM)
  - content_features → template suitability scores:
    • 3+ sub-topics → accordion: 0.8, tabs: 0.7
    • Q&A patterns → click-reveal: 0.9
    • Assessment keywords → final-assessment: 0.95
    • Single topic, narrative → content-text: 0.9
    • 2 parallel topics → tabs: 0.8
    • Callout/did-you-know pattern → content-text + callout component
  → Output: scored_templates per section

Pass 3: LLM Refinement (optional, any model size)
  - Only invoke LLM when scores are ambiguous (max score - second < 0.3)
  - LLM prompt: "This section has these features: {...}. 
    Top templates: [{type: score}, ...]. Choose the best one. Return JSON."
  - Small model: simple choice from pre-scored options
  - Large model: can override with creative choices
  → Output: final template assignment with confidence
```

**Key benefit:** Rules-based scoring works WITHOUT any LLM. LLM is only used for
ambiguous cases. This works from zero-LLM to frontier models.

### Solution C: Content Generation — Template-Specific Agents

**Current:** Single `ContentGeneratorAgent` for all templates.  
**Proposed:** Template-specific generation agents with model tiering:

| Template | Complexity | Min Model | Agent |
|---|---|---|---|
| `content-text` | Low | phi3:mini / qwen:3b | TextContentAgent — rich HTML with callouts |
| `accordion` | Medium | qwen2.5:7b | AccordionAgent — N panels with titles + content |
| `tabs` | Medium | qwen2.5:7b | TabsAgent — N tabs with titles + content |
| `click-reveal` | Medium | qwen2.5:7b | ClickRevealAgent — Q&A pairs |
| `final-assessment` | High | qwen2.5:7b+ | AssessmentAgent — structured MCQ JSON |

Each agent receives:
1. Template-specific schema contract
2. Few-shot examples of correct output
3. Content from source section
4. Course context (title, audience, tone, prerequisites)

**Structured output guarantee:**
```python
# Every agent MUST return this schema
{
    "components": [
        {
            "component_type": str,      # Must match template type
            "order_index": int,         # 0-based
            "data": {
                # Template-specific fields validated against schema
            }
        }
    ]
}
```

### Solution D: Assessment Generation — Dedicated Pipeline

**Current:** Mock fallback always for `final-assessment`.  
**Proposed:** Dedicated assessment generation pipeline:

```
1. Extract all page content (titles + key concepts)
2. Send to AssessmentAgent with structured prompt:
   "Generate {N} MCQ questions testing these concepts: [...]
    Each question must have:
    - A clear stem testing understanding (not recall)
    - 4 plausible options (1 correct, 3 distractors)
    - Topic-specific feedback for wrong answers
    - A reference to the source page"
3. Validate output against MCQ schema
4. If LLM fails → rules-based question generator:
   - Extract key terms from content
   - Generate definition-based MCQs from key terms
   - Generate true/false from facts
```

**Fallback for small models:**
```python
def _rule_based_mcq_generation(pages: list) -> list:
    """Extract key terms and generate basic MCQs without LLM."""
    questions = []
    for page in pages:
        # Extract key terms from h2/h3/strong tags
        # Generate "What is {term}?" definition questions
        # Generate "Which of the following is true about {topic}?"
    return questions
```

### Solution E: Multi-Component Page Structure

**Current:** Mock generator produces 1 component per page.  
**Proposed:** Component hierarchy detection:

```python
def _detect_component_structure(content_features: dict) -> list:
    """Determine component layout from content analysis."""
    components = []
    
    # Always start with a title/intro component
    components.append({"type": "content-text", "role": "intro"})
    
    # Add sub-components based on content features
    if content_features.get("has_callout"):
        components.append({"type": "content-text", "role": "callout"})
    
    if content_features.get("sub_topic_count", 0) >= 3:
        # Use interactive component for sub-topics
        components.append({"type": "accordion", "role": "sub_topics"})
    
    if content_features.get("has_image_refs"):
        components.append({"type": "content-media", "role": "media"})
    
    if content_features.get("has_key_takeaways"):
        components.append({"type": "content-text", "role": "summary"})
    
    return components
```

---

## 4. Recommended Solution — Progressive Implementation

### Phase 1: Zero-LLM Heuristics (immediate, no model dependency)

| Change | File | Effort |
|---|---|---|
| Add `_detect_content_features()` — typographic analysis | `document_extractor.py` | 3h |
| Add `_score_template_suitability()` — rules-based scoring | `ai_ingestion.py` (new `template_selector.py`) | 4h |
| Add `_rule_based_mcq_generation()` — extract-term MCQs | `course_generator.py` | 3h |
| Fix `_extract_text()` — use python-docx paragraph styles | `ingestion_service.py` | 2h |
| Add component structure detection | `course_generator.py` | 2h |
| **Total Phase 1** | | **14h** |

### Phase 2: Small LLM Enhancement (phi3:mini / qwen:3b)

| Change | File | Effort |
|---|---|---|
| Add template-specific generation prompts | `course_generator.py` | 4h |
| Add LLM refinement pass for ambiguous templates | `ai_ingestion.py` | 3h |
| Add semantic section boundary detection via LLM | `ingestion_service.py` | 3h |
| Add content review loop (generate → validate → retry) | `course_generator.py` | 4h |
| **Total Phase 2** | | **14h** |

### Phase 3: Large LLM Optimization (qwen2.5:7b+ / Claude)

| Change | File | Effort |
|---|---|---|
| Template-specific ContentGeneratorAgents | `app/services/ai/agents/` | 6h |
| AssessmentAgent with structured MCQ pipeline | `app/services/ai/agents/` | 4h |
| Multi-component page generation | `course_generator.py` | 4h |
| Model tiering router (complexity → model selection) | `app/services/ai/model_tier_router.py` | 3h |
| **Total Phase 3** | | **17h** |

---

## 5. Template Suitability Heuristics — Detailed Rules

```python
TEMPLATE_HEURISTICS = {
    "content-text": {
        "conditions": [
            "single_topic == True",
            "sub_topic_count < 3",
            "has_narrative_structure == True",
        ],
        "weight": 0.9,
    },
    "accordion": {
        "conditions": [
            "sub_topic_count >= 3",
            "sub_topics_independent == True",  # Can be read in any order
            "has_term_definitions == True",    # Glossary-like content
        ],
        "weight": 0.8,
    },
    "tabs": {
        "conditions": [
            "sub_topic_count >= 2",
            "sub_topics_parallel == True",     # Equal importance, different aspects
            "has_procedure_steps == True",     # How-to content
        ],
        "weight": 0.7,
    },
    "click-reveal": {
        "conditions": [
            "has_qa_pattern == True",          # Questions followed by answers
            "has_review_questions == True",    # Knowledge check
        ],
        "weight": 0.7,
    },
    "final-assessment": {
        "conditions": [
            "has_assessment_keywords == True", # "quiz", "test", "assessment"
            "section_position >= 0.8",         # Near end of document
            "has_questions == True",           # Actual question marks
        ],
        "weight": 0.95,
    },
    "welcome": {
        "conditions": [
            "section_position == 0",           # First section
            "has_intro_language == True",      # "welcome", "introduction", "overview"
        ],
        "weight": 0.9,
    },
    "summary": {
        "conditions": [
            "section_position >= 0.9",         # Near end
            "has_summary_language == True",    # "summary", "conclusion", "key takeaways"
            "is_before_assessment == True",
        ],
        "weight": 0.85,
    },
}
```

## 6. Content Feature Detection — Implementation

```python
import re

def detect_content_features(text: str, section_index: int, total_sections: int) -> dict:
    """Zero-LLM content feature extraction for template selection."""
    lines = text.strip().split("\n")
    
    return {
        # Structural
        "char_count": len(text),
        "line_count": len(lines),
        "paragraph_count": len([l for l in lines if l.strip() and not l.startswith("#")]),
        "avg_paragraph_length": sum(len(l) for l in lines) / max(len(lines), 1),
        
        # Heading detection
        "has_heading": bool(re.match(r'^#+\s|^[A-Z][\w\s]{5,50}$', lines[0].strip())) if lines else False,
        "heading_count": len([l for l in lines if re.match(r'^#+\s', l.strip())]),
        "bold_text_count": len(re.findall(r'\*\*.*?\*\*', text)),
        
        # Sub-topic detection
        "sub_topic_count": len([l for l in lines if re.match(r'^(#+|\d+\.|[A-Z][\w\s]{3,40}:)', l.strip())]),
        "sub_topics_independent": _check_independent_subtopics(lines),
        "sub_topics_parallel": _check_parallel_subtopics(lines),
        
        # Content patterns
        "has_qa_pattern": bool(re.search(r'Q:.*\n.*A:|^\?.*\n|What\s+is.*\?', text, re.MULTILINE)),
        "has_list": bool(re.search(r'^[\-\*\•]\s|^\d+[\.\)]\s', text, re.MULTILINE)),
        "has_callout": bool(re.search(r'(Note|Tip|Warning|Important|Did you know|Key Takeaway)', text, re.IGNORECASE)),
        "has_image_refs": bool(re.search(r'!\[|\[image\]|\[figure\]|\(fig|\(see', text, re.IGNORECASE)),
        "has_table": "|" in text and "---" in text,
        
        # Semantic keywords
        "has_intro_language": bool(re.search(r'\b(welcome|introduction|overview|getting started)\b', text, re.IGNORECASE)),
        "has_summary_language": bool(re.search(r'\b(summary|conclusion|key takeaways?|in summary|to summarize)\b', text, re.IGNORECASE)),
        "has_assessment_keywords": bool(re.search(r'\b(quiz|test|assessment|check your (knowledge|understanding)|evaluation)\b', text, re.IGNORECASE)),
        "has_term_definitions": bool(re.search(r'\b(\w[\w\s]{2,30})\s*[:\-—]\s*.{10,}', text)),
        "has_procedure_steps": bool(re.search(r'(step\s+\d|first|next|then|finally|1\.\s.*\n2\.\s)', text, re.IGNORECASE)),
        "has_narrative_structure": len(text) > 500 and len([l for l in lines if l.strip()]) > 3,
        
        # Position
        "section_position": section_index / max(total_sections, 1),
        "is_first": section_index == 0,
        "is_last": section_index == total_sections - 1,
        "is_before_assessment": section_index == total_sections - 2,
    }
```

## 7. Model Tiering Router

```python
TEMPLATE_MODEL_TIER = {
    # Templates that work with small models
    "content-text": "small",     # phi3:mini / qwen:3b
    "welcome": "small",
    "summary": "small",
    
    # Templates that need mid models
    "accordion": "mid",          # qwen2.5:7b
    "tabs": "mid",
    "click-reveal": "mid",
    "content-video": "mid",
    "content-media": "mid",
    
    # Templates that need large models
    "final-assessment": "large", # qwen2.5:7b+ / claude
    "mcq": "large",
}

def resolve_model_for_template(template_type: str, available_models: list) -> str:
    """Pick the right model tier for a template, falling back gracefully."""
    required_tier = TEMPLATE_MODEL_TIER.get(template_type, "mid")
    
    if required_tier == "small":
        return available_models[0]  # Any model works
    
    if required_tier == "mid":
        # Prefer 7B+, fall back to available
        mid_models = [m for m in available_models if "7b" in m.lower() or "13b" in m.lower()]
        return mid_models[0] if mid_models else available_models[-1]
    
    if required_tier == "large":
        # Prefer largest available, fall back with reduced expectations
        return available_models[-1]  # Largest available
```

## 8. Verification Plan

### Unit Tests
- `test_content_feature_detection_*`: 10 test cases for feature extraction
- `test_template_scoring_*`: 5 test cases for heuristics scoring
- `test_model_tier_routing_*`: 3 test cases for model selection
- `test_rule_based_mcq_*`: 3 test cases for MCQ generation

### Integration Tests
- Upload real DOCX → verify section extraction quality
- Propose breakdown → verify template distribution (not all content-text)
- Generate course → verify 0 mock fallbacks for assessment
- Compare old vs new pipeline on same SB2 docx

### Quality Metrics
| Metric | Current | Target |
|---|---|---|
| Template diversity (non-content-text ratio) | 10% | ≥ 40% |
| Assessment mock fallback rate | 100% | ≤ 5% |
| Multi-component page ratio | 0% | ≥ 30% |
| Section extraction accuracy | Poor | Good (distinct previews per section) |
| Interactive template usage | 0% | ≥ 30% |

---

## 9. Implementation Priority

| Priority | Phase | What | Why |
|---|---|---|---|
| **P0** | Phase 1 | Content feature detection | Enables all downstream improvements, zero LLM dependency |
| **P0** | Phase 1 | Fix section extraction | Garbage in → garbage out. Root of template selection problem |
| **P0** | Phase 1 | Template heuristics engine | Stops blind content-text assignment |
| **P1** | Phase 2 | Template-specific prompts | Better content quality per template type |
| **P1** | Phase 2 | Rule-based MCQ generation | Eliminates mock fallback for assessment |
| **P2** | Phase 3 | Multi-component pages | Richer page structure |
| **P2** | Phase 3 | Model tiering router | Right model for each template complexity |
