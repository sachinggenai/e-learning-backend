"""Standalone test runner for MarkedDocumentParser — Template Marking System.

Tests the deterministic marker parser that extracts [PAGE:], [COMPONENT:],
[ITEM:], [QUESTION:], [OPTION:], and [FEEDBACK] markers from DOCX paragraph
data. Covers detection, parsing, validation, error handling, nested markers,
and integration scenarios.

Usage:
    PYTHONPATH=. python tests/run_marked_parser_tests.py

TRD: Template Marking System v1.0
FRD: FRD-TMS-001
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.ai.marked_document_parser import (
    MarkedDocumentParser,
    MarkedDocument,
    MarkedPage,
    MarkedComponent,
    MarkedItem,
    ParseError,
    ParseLocation,
    ERROR_CODES,
)

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append((name, detail))


def make_paragraphs(*texts):
    """Helper: create paragraph dicts from text strings."""
    return [{"text": t} for t in texts]


# ═══════════════════════════════════════════════════════════════════════════
# 1. Marker Detection Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_detection():
    print("\n-- Marker Detection --")
    p = MarkedDocumentParser()

    # 1.1: Detects PAGE marker
    paras = make_paragraphs("[PAGE: content-text | title: Test]")
    check("detects_page_marker", p.has_markers(paras))

    # 1.2: No markers in empty
    check("no_markers_empty", not p.has_markers([]))

    # 1.3: No markers in plain text
    paras = make_paragraphs("Hello world", "Plain text here")
    check("no_markers_plain_text", not p.has_markers(paras))

    # 1.4: No markers in MD headings
    paras = make_paragraphs("# Section 1", "## Subsection", "content")
    check("no_markers_md_headings", not p.has_markers(paras))

    # 1.5: Detects marker in later paragraph
    paras = make_paragraphs("intro text", "[PAGE: content-text | title: Page 1]")
    check("detects_marker_in_later_para", p.has_markers(paras))

    # 1.6: No false positive on bracket-like text
    paras = make_paragraphs("[reference]", "[note: something]", "[source: abc]")
    check("no_false_positive_brackets", not p.has_markers(paras))

    # 1.7: Detects all 7 template types
    for ttype in ["content-text", "tabs", "accordion", "click-reveal",
                   "final-assessment", "welcome", "summary"]:
        paras = make_paragraphs(f"[PAGE: {ttype} | title: Test]")
        check(f"detects_template_{ttype}", p.has_markers(paras))


# ═══════════════════════════════════════════════════════════════════════════
# 2. Page Marker Parsing Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_page_parsing():
    print("\n-- Page Parsing --")
    p = MarkedDocumentParser()

    # 2.1: Basic page with component
    paras = make_paragraphs(
        "[PAGE: content-text | title: Intro]",
        "[COMPONENT: content-text]Hello[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("parses_basic_page", len(doc.pages) == 1)
    check("parses_basic_page_title", doc.pages[0].title == "Intro")
    check("parses_basic_page_template", doc.pages[0].template_type == "content-text")
    check("parses_basic_page_components", len(doc.pages[0].components) == 1)

    # 2.2: Page with order attribute
    paras = make_paragraphs(
        "[PAGE: tabs | title: TabPage | order: 5]",
        "[COMPONENT: tabs][/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("parses_page_order", doc.pages[0].order == 5)

    # 2.3: All 7 template types accepted
    for ttype in ["content-text", "tabs", "accordion", "click-reveal",
                   "final-assessment", "welcome", "summary"]:
        paras = make_paragraphs(
            f"[PAGE: {ttype} | title: {ttype}]",
            f"[COMPONENT: content-text]test[/COMPONENT]",
            "[/PAGE]",
        )
        doc = p.parse(paras)
        check(f"parses_{ttype}", doc.pages[0].template_type == ttype)

    # 2.4: Page without title (auto-generated)
    paras = make_paragraphs(
        "[PAGE: content-text]",
        "[COMPONENT: content-text]test[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("auto_generates_title", doc.pages[0].title.startswith("Page "))

    # 2.5: Multiple pages
    paras = make_paragraphs(
        "[PAGE: content-text | title: Page1]",
        "[COMPONENT: content-text]A[/COMPONENT]",
        "[/PAGE]",
        "[PAGE: content-text | title: Page2]",
        "[COMPONENT: content-text]B[/COMPONENT]",
        "[/PAGE]",
        "[PAGE: content-text | title: Page3]",
        "[COMPONENT: content-text]C[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("parses_multiple_pages", len(doc.pages) == 3)
    check("pages_in_order", [p.title for p in doc.pages] == ["Page1", "Page2", "Page3"])

    # 2.6: Invalid template type
    paras = make_paragraphs("[PAGE: invalid_type | title: Bad]")
    doc = p.parse(paras)
    has_invalid = any(e.code == "INVALID_TEMPLATE_TYPE" for e in doc.parse_errors)
    check("invalid_template_type_error", has_invalid)

    # 2.7: Unclosed page marker
    paras = make_paragraphs("[PAGE: content-text | title: Open]")
    doc = p.parse(paras)
    has_unclosed = any(e.code == "UNCLOSED_MARKER" for e in doc.parse_errors)
    check("unclosed_page_marker", has_unclosed)

    # 2.8: Empty page warning
    paras = make_paragraphs(
        "[PAGE: content-text | title: Empty]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    has_empty = any(e.code == "EMPTY_PAGE" for e in doc.parse_errors)
    check("empty_page_warning", has_empty)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Component Marker Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_component_parsing():
    print("\n-- Component Parsing --")
    p = MarkedDocumentParser()

    # 3.1: Content-text component with raw_content
    paras = make_paragraphs(
        "[PAGE: content-text | title: Test]",
        "[COMPONENT: content-text]body text here[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    comp = doc.pages[0].components[0]
    check("parses_content_text", comp.component_type == "content-text")
    check("captures_raw_content", "body text here" in comp.raw_content)

    # 3.2: Tabs component with items
    paras = make_paragraphs(
        "[PAGE: tabs | title: TabTest]",
        "[COMPONENT: tabs]",
        "[ITEM: Tab A]Content A[/ITEM]",
        "[ITEM: Tab B]Content B[/ITEM]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    comp = doc.pages[0].components[0]
    check("parses_tabs_component", comp.component_type == "tabs")
    check("tabs_has_2_items", len(comp.items) == 2)
    check("tab_items_have_type", all(i.item_type == "tab" for i in comp.items))
    check("tab_items_have_content", all(i.content for i in comp.items))

    # 3.3: Accordion component
    paras = make_paragraphs(
        "[PAGE: accordion | title: FAQ]",
        "[COMPONENT: accordion]",
        "[ITEM: Q1]Answer 1[/ITEM]",
        "[ITEM: Q2]Answer 2[/ITEM]",
        "[ITEM: Q3]Answer 3[/ITEM]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    comp = doc.pages[0].components[0]
    check("parses_accordion", comp.component_type == "accordion")
    check("accordion_has_3_items", len(comp.items) == 3)
    check("accordion_item_types", all(i.item_type == "accordion-item" for i in comp.items))

    # 3.4: Invalid component type
    paras = make_paragraphs(
        "[PAGE: content-text | title: Test]",
        "[COMPONENT: carousel]bad[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    has_invalid = any(e.code == "INVALID_COMPONENT_TYPE" for e in doc.parse_errors)
    check("invalid_component_type_error", has_invalid)

    # 3.5: Empty component warning
    paras = make_paragraphs(
        "[PAGE: content-text | title: Test]",
        "[COMPONENT: content-text][/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    has_empty = any(e.code == "EMPTY_COMPONENT" for e in doc.parse_errors)
    check("empty_component_warning", has_empty)

    # 3.6: Component with custom attributes
    paras = make_paragraphs(
        "[PAGE: content-text | title: Test]",
        "[COMPONENT: content-text | lang: en]hello[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    attrs = doc.pages[0].components[0].attributes
    check("component_attributes", attrs.get("lang") == "en")


# ═══════════════════════════════════════════════════════════════════════════
# 4. Assessment Question Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_assessment_parsing():
    print("\n-- Assessment Parsing --")
    p = MarkedDocumentParser()

    # 4.1: Full MCQ with options and feedback
    paras = make_paragraphs(
        "[PAGE: final-assessment | title: Quiz]",
        "[COMPONENT: final-assessment | passing_score: 80]",
        "[QUESTION: mcq | id: q1]",
        "What is the capital of France?",
        "[OPTION: a | correct: true]Paris[/OPTION]",
        "[OPTION: b]London[/OPTION]",
        "[OPTION: c]Berlin[/OPTION]",
        "[FEEDBACK]Paris is the capital.[/FEEDBACK]",
        "[/QUESTION]",
        "[QUESTION: mcq | id: q2]",
        "What is 2+2?",
        "[OPTION: a]3[/OPTION]",
        "[OPTION: b | correct: true]4[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq | id: q3]",
        "Is the sky blue?",
        "[OPTION: a | correct: true]Yes[/OPTION]",
        "[OPTION: b]No[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("assessment_no_errors", len(doc.parse_errors) == 0,
          f"got {len(doc.parse_errors)} errors")
    comp = doc.pages[0].components[0]
    questions = [i for i in comp.items if i.item_type == "question"]
    check("assessment_has_3_questions", len(questions) == 3)

    # Check q1 details
    q1 = questions[0]
    q1_opts = [c for c in q1.metadata.get("_children", []) if c.item_type == "option"]
    q1_fb = [c for c in q1.metadata.get("_children", []) if c.item_type == "feedback"]
    q1_correct = [o for o in q1_opts if o.metadata.get("is_correct")]
    check("q1_has_3_options", len(q1_opts) == 3)
    check("q1_has_1_correct", len(q1_correct) == 1)
    check("q1_has_feedback", len(q1_fb) == 1)

    # Check q2 details
    q2 = questions[1]
    q2_opts = [c for c in q2.metadata.get("_children", []) if c.item_type == "option"]
    q2_correct = [o for o in q2_opts if o.metadata.get("is_correct")]
    check("q2_has_2_options", len(q2_opts) == 2)
    check("q2_has_1_correct", len(q2_correct) == 1)

    # 4.2: True-false question
    paras = make_paragraphs(
        "[PAGE: final-assessment | title: TFQuiz]",
        "[COMPONENT: final-assessment]",
        "[QUESTION: true-false | id: tf1]",
        "The Earth is flat.",
        "[OPTION: a]True[/OPTION]",
        "[OPTION: b | correct: true]False[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: true-false | id: tf2]",
        "Water is wet.",
        "[OPTION: a | correct: true]True[/OPTION]",
        "[OPTION: b]False[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: true-false | id: tf3]",
        "Python is a snake.",
        "[OPTION: a]True[/OPTION]",
        "[OPTION: b | correct: true]False[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("true_false_no_errors", len(doc.parse_errors) == 0,
          f"got {len(doc.parse_errors)} errors")
    qs = [i for i in doc.pages[0].components[0].items if i.item_type == "question"]
    check("true_false_3_questions", len(qs) == 3)

    # 4.3: Missing correct answer
    paras = make_paragraphs(
        "[PAGE: final-assessment | title: BadQuiz]",
        "[COMPONENT: final-assessment]",
        "[QUESTION: mcq | id: q1]No correct answer",
        "[OPTION: a]Wrong[/OPTION]",
        "[OPTION: b]Also wrong[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq | id: q2]Still no correct",
        "[OPTION: a]Nope[/OPTION]",
        "[OPTION: b]Nada[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq | id: q3]Also no correct",
        "[OPTION: a]Never[/OPTION]",
        "[OPTION: b]Nope[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    has_missing = any(e.code == "MISSING_CORRECT_ANSWER" for e in doc.parse_errors)
    check("detects_missing_correct_answer", has_missing)

    # 4.4: Too few questions
    paras = make_paragraphs(
        "[PAGE: final-assessment | title: TinyQuiz]",
        "[COMPONENT: final-assessment]",
        "[QUESTION: mcq]One question only",
        "[OPTION: a | correct: true]Yes[/OPTION]",
        "[OPTION: b]No[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    has_few = any(e.code == "TOO_FEW_QUESTIONS" for e in doc.parse_errors)
    check("detects_too_few_questions", has_few)

    # 4.5: Too few options
    paras = make_paragraphs(
        "[PAGE: final-assessment | title: BadOpts]",
        "[COMPONENT: final-assessment]",
        "[QUESTION: mcq]Only one option",
        "[OPTION: a | correct: true]Solo[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq]Also one",
        "[OPTION: a | correct: true]Single[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq]Yet another one",
        "[OPTION: a | correct: true]One[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    has_few_opts = any(e.code == "TOO_FEW_OPTIONS" for e in doc.parse_errors)
    check("detects_too_few_options", has_few_opts)

    # 4.6: Passing score attribute
    paras = make_paragraphs(
        "[PAGE: final-assessment | title: Scored]",
        "[COMPONENT: final-assessment | passing_score: 85]",
        "[QUESTION: mcq]Q1",
        "[OPTION: a | correct: true]Yes[/OPTION]",
        "[OPTION: b]No[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq]Q2",
        "[OPTION: a | correct: true]Certainly[/OPTION]",
        "[OPTION: b]Nope[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq]Q3",
        "[OPTION: a | correct: true]Yep[/OPTION]",
        "[OPTION: b]Nah[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("passing_score_attribute",
          doc.pages[0].components[0].attributes.get("passing_score") == "85")


# ═══════════════════════════════════════════════════════════════════════════
# 5. Nested Marker Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_nested_markers():
    print("\n-- Nested Markers --")
    p = MarkedDocumentParser()

    # 5.1: Standard PAGE > COMPONENT > ITEM hierarchy
    paras = make_paragraphs(
        "[PAGE: tabs | title: Hierarchical]",
        "[COMPONENT: tabs]",
        "[ITEM: Tab 1]Content 1[/ITEM]",
        "[ITEM: Tab 2]Content 2[/ITEM]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("standard_hierarchy_no_errors", len(doc.parse_errors) == 0,
          f"got {len(doc.parse_errors)}")
    check("standard_hierarchy_depth", len(doc.pages) == 1 and
          len(doc.pages[0].components) == 1 and
          len(doc.pages[0].components[0].items) == 2)

    # 5.2: PAGE inside PAGE (nested pages)
    paras = make_paragraphs(
        "[PAGE: content-text | title: Parent]",
        "[COMPONENT: content-text]Parent content[/COMPONENT]",
        "[PAGE: content-text | title: Child]",
        "[COMPONENT: content-text]Child content[/COMPONENT]",
        "[/PAGE]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    # Nested pages should produce multi-page output
    check("nested_pages_produces_output", len(doc.pages) >= 1)

    # 5.3: Multi-page document with different template types
    paras = make_paragraphs(
        "[PAGE: content-text | title: Intro]",
        "[COMPONENT: content-text]Welcome[/COMPONENT]",
        "[/PAGE]",
        "[PAGE: accordion | title: Details]",
        "[COMPONENT: accordion]",
        "[ITEM: Detail 1]Info 1[/ITEM]",
        "[ITEM: Detail 2]Info 2[/ITEM]",
        "[/COMPONENT]",
        "[/PAGE]",
        "[PAGE: final-assessment | title: Quiz]",
        "[COMPONENT: final-assessment]",
        "[QUESTION: mcq]Is this correct?",
        "[OPTION: a | correct: true]Yes[/OPTION]",
        "[OPTION: b]No[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq]Another one?",
        "[OPTION: a | correct: true]Yep[/OPTION]",
        "[OPTION: b]Nope[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq]Third one?",
        "[OPTION: a | correct: true]Indeed[/OPTION]",
        "[OPTION: b]Nah[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("multi_page_mixed_templates_no_errors", len(doc.parse_errors) == 0,
          f"got {len(doc.parse_errors)}")
    check("multi_page_3_pages", len(doc.pages) == 3)
    check("multi_page_templates",
          [p.template_type for p in doc.pages] ==
          ["content-text", "accordion", "final-assessment"])


# ═══════════════════════════════════════════════════════════════════════════
# 6. Error Handling Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_error_handling():
    print("\n-- Error Handling --")
    p = MarkedDocumentParser()

    # 6.1: UNCLOSED_MARKER
    doc = p.parse(make_paragraphs("[PAGE: content-text | title: Open]"))
    check("error_UNCLOSED_MARKER",
          any(e.code == "UNCLOSED_MARKER" for e in doc.parse_errors))

    # 6.2: UNEXPECTED_CLOSE — close marker before any open (empty stack)
    doc = p.parse(make_paragraphs(
        "[/COMPONENT]",  # Stray close BEFORE any PAGE — empty stack
        "[PAGE: content-text | title: Test]",
        "[COMPONENT: content-text]content[/COMPONENT]",
        "[/PAGE]",
    ))
    check("error_UNEXPECTED_CLOSE",
          any(e.code == "UNEXPECTED_CLOSE" for e in doc.parse_errors))

    # 6.3: MISMATCHED_CLOSE
    doc = p.parse(make_paragraphs(
        "[PAGE: content-text | title: Test]",
        "[COMPONENT: content-text]content[/COMPONENT]",
        "[/ITEM]",  # Wrong close type
        "[/PAGE]",
    ))
    check("error_MISMATCHED_CLOSE",
          any(e.code == "MISMATCHED_CLOSE" for e in doc.parse_errors))

    # 6.4: NESTING_VIOLATION
    doc = p.parse(make_paragraphs(
        "[PAGE: content-text | title: Test]",
        "[COMPONENT: content-text]",
        "[PAGE: tabs | title: Nested]",  # PAGE inside COMPONENT? Actually PAGE inside COMPONENT is allowed by nesting rules now
        "[/PAGE]",
        "[/COMPONENT]",
        "[/PAGE]",
    ))
    # PAGE inside COMPONENT is now allowed in nesting rules
    check("page_inside_component_allowed", len(doc.pages) >= 1)

    # 6.5: DUPLICATE_PAGE_TITLE
    doc = p.parse(make_paragraphs(
        "[PAGE: content-text | title: Same]",
        "[COMPONENT: content-text]A[/COMPONENT]",
        "[/PAGE]",
        "[PAGE: content-text | title: Same]",
        "[COMPONENT: content-text]B[/COMPONENT]",
        "[/PAGE]",
    ))
    check("warning_DUPLICATE_PAGE_TITLE",
          any(e.code == "DUPLICATE_PAGE_TITLE" for e in doc.parse_errors))

    # 6.6: INVALID_TEMPLATE_TYPE
    doc = p.parse(make_paragraphs("[PAGE: unknown-type | title: Bad]"))
    check("error_INVALID_TEMPLATE_TYPE",
          any(e.code == "INVALID_TEMPLATE_TYPE" for e in doc.parse_errors))

    # 6.7: MISSING_CORRECT_ANSWER
    doc = p.parse(make_paragraphs(
        "[PAGE: final-assessment | title: BadQuiz]",
        "[COMPONENT: final-assessment]",
        "[QUESTION: mcq]No correct",
        "[OPTION: a]Wrong[/OPTION]",
        "[OPTION: b]Also wrong[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq]Q2",
        "[OPTION: a]Nope[/OPTION]",
        "[OPTION: b]Nada[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq]Q3",
        "[OPTION: a]Never[/OPTION]",
        "[OPTION: b]No[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    ))
    check("error_MISSING_CORRECT_ANSWER",
          any(e.code == "MISSING_CORRECT_ANSWER" for e in doc.parse_errors))

    # 6.8: TOO_MANY_ITEMS (tabs > 6) — each ITEM on separate paragraph
    paras = [
        {'text': '[PAGE: tabs | title: TooMany]'},
        {'text': '[COMPONENT: tabs]'},
    ]
    for i in range(7):
        paras.append({'text': f'[ITEM: Tab{i}]Content{i}[/ITEM]'})
    paras.append({'text': '[/COMPONENT]'})
    paras.append({'text': '[/PAGE]'})
    doc = p.parse(paras)
    check("warning_TOO_MANY_ITEMS",
          any(e.code == "TOO_MANY_ITEMS" for e in doc.parse_errors))


# ═══════════════════════════════════════════════════════════════════════════
# 7. Unmarked Document Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_unmarked_documents():
    print("\n-- Unmarked Documents --")
    p = MarkedDocumentParser()

    # 7.1: Plain text — no markers
    doc = p.parse(make_paragraphs(
        "This is a plain text document.",
        "It has multiple paragraphs.",
        "But no markers at all.",
    ))
    check("plain_text_no_markers", not doc.has_markers)
    check("plain_text_zero_pages", len(doc.pages) == 0)
    check("plain_text_unmarked_paras", len(doc.unmarked_paragraphs) == 3)

    # 7.2: MD headings — no markers
    doc = p.parse(make_paragraphs(
        "# Module 1",
        "## Lesson 1",
        "Content here",
        "## Lesson 2",
        "More content",
    ))
    check("md_headings_no_markers", not doc.has_markers)

    # 7.3: Heuristic-style headings (SECTION X —) — no markers
    doc = p.parse(make_paragraphs(
        "SECTION 1 — Introduction",
        "This is the first section.",
        "SECTION 2 — Main Content",
        "This is the second section.",
    ))
    check("heuristic_headings_no_markers", not doc.has_markers)

    # 7.4: Escaped markers treated as text
    doc = p.parse(make_paragraphs(
        "\\[PAGE: content-text\\] This is literal text, not a marker.",
        "More content.",
    ))
    check("escaped_markers_not_detected", not doc.has_markers)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Serialization Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_serialization():
    print("\n-- Serialization --")
    p = MarkedDocumentParser()

    # 8.1: Round-trip to_dict → from_dict
    paras = make_paragraphs(
        "[PAGE: tabs | title: Serialize]",
        "[COMPONENT: tabs]",
        "[ITEM: Tab 1]Content 1[/ITEM]",
        "[ITEM: Tab 2]Content 2[/ITEM]",
        "[/COMPONENT]",
        "[/PAGE]",
        "[PAGE: content-text | title: Second]",
        "[COMPONENT: content-text]Hello[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("roundtrip_no_errors", len(doc.parse_errors) == 0,
          f"got {len(doc.parse_errors)} errors")
    d = doc.to_dict()
    check("to_dict_has_pages", len(d["pages"]) == 2)

    doc2 = MarkedDocument.from_dict(d)
    check("from_dict_has_markers", doc2.has_markers)
    check("from_dict_pages", len(doc2.pages) == 2)
    check("from_dict_page_titles",
          [pg.title for pg in doc2.pages] == ["Serialize", "Second"])
    check("from_dict_templates",
          [pg.template_type for pg in doc2.pages] == ["tabs", "content-text"])

    # 8.2: Empty document round-trip
    d_empty = MarkedDocument(has_markers=False)
    check("empty_to_dict", d_empty.to_dict()["has_markers"] is False)
    doc_empty = MarkedDocument.from_dict({"has_markers": False})
    check("empty_from_dict", not doc_empty.has_markers)

    # 8.3: Assessment round-trip
    paras = make_paragraphs(
        "[PAGE: final-assessment | title: Quiz]",
        "[COMPONENT: final-assessment | passing_score: 80]",
        "[QUESTION: mcq | id: q1]",
        "Capital of France?",
        "[OPTION: a | correct: true]Paris[/OPTION]",
        "[OPTION: b]London[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq | id: q2]2+2?",
        "[OPTION: a]3[/OPTION]",
        "[OPTION: b | correct: true]4[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq | id: q3]Sky color?",
        "[OPTION: a | correct: true]Blue[/OPTION]",
        "[OPTION: b]Green[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("assessment_roundtrip_no_errors", len(doc.parse_errors) == 0,
          f"got {len(doc.parse_errors)} errors")
    d = doc.to_dict()
    doc2 = MarkedDocument.from_dict(d)
    check("assessment_roundtrip_pages", len(doc2.pages) == 1)
    qs = [i for i in doc2.pages[0].components[0].items if i.item_type == "question"]
    check("assessment_roundtrip_questions", len(qs) == 3)


# ═══════════════════════════════════════════════════════════════════════════
# 9. Integration Scenario Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_integration_scenarios():
    print("\n-- Integration Scenarios --")
    p = MarkedDocumentParser()

    # 9.1: Complete cybersecurity training course structure
    paras = make_paragraphs(
        # Welcome page
        "[PAGE: welcome | title: Welcome]",
        "[COMPONENT: content-text]Welcome to Cybersecurity Awareness Training.[/COMPONENT]",
        "[/PAGE]",
        # Content page with accordion
        "[PAGE: accordion | title: Phishing Attack Types]",
        "[COMPONENT: content-text]Phishing is a form of social engineering...[/COMPONENT]",
        "[COMPONENT: accordion]",
        "[ITEM: Spear Phishing]Targeted attacks directed at specific individuals or organizations.[/ITEM]",
        "[ITEM: Whaling]Attacks targeting senior executives and high-value individuals.[/ITEM]",
        "[ITEM: Clone Phishing]A legitimate email is copied and modified with malicious links.[/ITEM]",
        "[ITEM: Vishing]Voice phishing — using phone calls to extract sensitive information.[/ITEM]",
        "[/COMPONENT]",
        "[/PAGE]",
        # Tabs page
        "[PAGE: tabs | title: Comparing Security Approaches]",
        "[COMPONENT: tabs]",
        "[ITEM: Prevention]Proactive measures to prevent attacks before they occur.[/ITEM]",
        "[ITEM: Detection]Monitoring systems to detect attacks in progress.[/ITEM]",
        "[ITEM: Response]Procedures to follow when a security incident is detected.[/ITEM]",
        "[/COMPONENT]",
        "[/PAGE]",
        # Assessment page
        "[PAGE: final-assessment | title: Knowledge Check]",
        "[COMPONENT: final-assessment | passing_score: 80]",
        "[QUESTION: mcq | id: q1]Which type of phishing targets executives?",
        "[OPTION: a]Spear Phishing[/OPTION]",
        "[OPTION: b | correct: true]Whaling[/OPTION]",
        "[OPTION: c]Clone Phishing[/OPTION]",
        "[OPTION: d]Vishing[/OPTION]",
        "[FEEDBACK]Whaling specifically targets senior executives and high-value individuals.[/FEEDBACK]",
        "[/QUESTION]",
        "[QUESTION: mcq | id: q2]What is the best defense against phishing?",
        "[OPTION: a]Installing antivirus[/OPTION]",
        "[OPTION: b]Using a firewall[/OPTION]",
        "[OPTION: c | correct: true]Security awareness training[/OPTION]",
        "[OPTION: d]Changing passwords daily[/OPTION]",
        "[/QUESTION]",
        "[QUESTION: mcq | id: q3]Clone phishing involves...",
        "[OPTION: a]Calling the victim[/OPTION]",
        "[OPTION: b | correct: true]Copying a legitimate email with malicious modifications[/OPTION]",
        "[OPTION: c]Attacking via social media[/OPTION]",
        "[OPTION: d]Physical theft of credentials[/OPTION]",
        "[/QUESTION]",
        "[/COMPONENT]",
        "[/PAGE]",
        # Summary page
        "[PAGE: summary | title: Key Takeaways]",
        "[COMPONENT: content-text]Remember the key principles of cybersecurity...[/COMPONENT]",
        "[/PAGE]",
    )
    doc = p.parse(paras)
    check("full_course_no_errors", len(doc.parse_errors) == 0,
          f"got {len(doc.parse_errors)} errors")
    check("full_course_5_pages", len(doc.pages) == 5)
    check("full_course_templates", [
        p.template_type for p in doc.pages
    ] == ["welcome", "accordion", "tabs", "final-assessment", "summary"])
    check("full_course_accordion_has_2_components",
          len(doc.pages[1].components) == 2)
    check("full_course_accordion_4_items",
          len(doc.pages[1].components[1].items) == 4)
    check("full_course_tabs_3_items",
          len(doc.pages[2].components[0].items) == 3)

    qs = [i for i in doc.pages[3].components[0].items if i.item_type == "question"]
    check("full_course_3_questions", len(qs) == 3)

    # 9.2: to_dict serialization works on full course
    d = doc.to_dict()
    check("full_course_to_dict", d["has_markers"] is True)
    check("full_course_to_dict_pages", len(d["pages"]) == 5)

    doc2 = MarkedDocument.from_dict(d)
    check("full_course_roundtrip_pages", len(doc2.pages) == 5)

    # 9.3: Verify no errors in ERROR_CODES registry
    for code in ERROR_CODES:
        check(f"error_code_{code}_has_severity", "severity" in ERROR_CODES[code])
        check(f"error_code_{code}_has_description", "description" in ERROR_CODES[code])
        check(f"error_code_{code}_has_suggestion", "suggestion" in ERROR_CODES[code])


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main():
    print("=" * 60)
    print("MarkedDocumentParser — Template Marking System Tests")
    print("=" * 60)

    test_detection()
    test_page_parsing()
    test_component_parsing()
    test_assessment_parsing()
    test_nested_markers()
    test_error_handling()
    test_unmarked_documents()
    test_serialization()
    test_integration_scenarios()

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    if failures:
        print(f"Failures:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
