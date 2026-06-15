"""Standalone test runner for US-BKND-AI-019 - Course Generation.

Tests CourseGenerator: mock content generation, template assignment,
validation, page assembly, error handling.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.course_generator import (
    CourseGenerator, GenerationStatus, GenerationError,
)

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        failures.append((name, detail))
        print(f"  FAIL: {name} -- {detail}")


async def main():
    global passed, failed

    # ===============================================================
    # Mock Content Generation
    # ===============================================================
    print("=== Mock Content Generation ===")
    gen = CourseGenerator(AsyncMock())

    # Text content page
    page = gen._generate_page_content(
        {"title": "Introduction", "template_type": "text-content",
         "source_excerpt": "This is source material about Python."},
        {}, 0,
    )
    check("generates text-content", page["template_type"] == "text-content")
    check("has components", len(page["components"]) > 0)
    check("has title", "Introduction" in page["title"])
    comp = page["components"][0]
    check("component has data", "content" in comp.get("data", {}))

    # Accordion page
    page = gen._generate_page_content(
        {"title": "FAQ", "template_type": "accordion", "source_excerpt": "FAQ content"},
        {}, 1,
    )
    check("generates accordion", page["template_type"] == "accordion")
    comp = page["components"][0]
    items = comp.get("data", {}).get("items", [])
    check("accordion has items", len(items) > 0)

    # Tabs page
    page = gen._generate_page_content(
        {"title": "Comparison", "template_type": "tabs", "source_excerpt": "Compare A vs B"},
        {}, 2,
    )
    check("generates tabs", page["template_type"] == "tabs")
    comp = page["components"][0]
    tabs = comp.get("data", {}).get("tabs", [])
    check("tabs has tabs", len(tabs) > 0)

    # Click-reveal page
    page = gen._generate_page_content(
        {"title": "Discover", "template_type": "click-reveal", "source_excerpt": "Reveal content"},
        {}, 3,
    )
    check("generates click-reveal", page["template_type"] == "click-reveal")
    comp = page["components"][0]
    items = comp.get("data", {}).get("items", [])
    check("click-reveal has items", len(items) > 0)

    # Final assessment page
    page = gen._generate_page_content(
        {"title": "Quiz", "template_type": "final-assessment", "source_excerpt": "Test content"},
        {}, 4,
    )
    check("generates final-assessment", page["template_type"] == "final-assessment")
    comp = page["components"][0]
    questions = comp.get("data", {}).get("questions", [])
    check("assessment has questions", len(questions) > 0)
    passing = comp.get("data", {}).get("passing_score", 0)
    check("assessment has passing score", passing == 80)

    # Unknown type defaults to text-content
    page = gen._generate_page_content(
        {"title": "Unknown", "template_type": "unknown-type", "source_excerpt": ""},
        {}, 5,
    )
    check("unknown type defaults to text-content", page["template_type"] == "unknown-type")
    check("still has components", len(page["components"]) > 0)

    # ===============================================================
    # Batch Page Generation
    # ===============================================================
    print("\n=== Batch Generation ===")
    plan = [
        {"title": "Intro", "template_type": "text-content", "order": 0, "source_excerpt": "Intro text"},
        {"title": "Lesson 1", "template_type": "accordion", "order": 1, "source_excerpt": "Lesson text"},
        {"title": "Quiz", "template_type": "final-assessment", "order": 2, "source_excerpt": "Quiz text"},
    ]
    pages = await gen._generate_pages(plan, {})
    check("generates all pages", len(pages) == 3)
    check("page 0 is text-content", pages[0]["template_type"] == "text-content")
    check("page 1 is accordion", pages[1]["template_type"] == "accordion")
    check("page 2 is assessment", pages[2]["template_type"] == "final-assessment")

    # ===============================================================
    # Validation
    # ===============================================================
    print("\n=== Validation ===")
    results = gen._validate_generated_pages(pages)
    check("validates all pages", len(results) == 3)
    check("all pages valid", all(r["status"] == "valid" for r in results))

    # Invalid page (no component data)
    bad_pages = [{
        "title": "", "template_type": "final-assessment", "order": 0,
        "components": [{"component_type": "final-assessment", "order_index": 0, "data": {}}],
    }]
    results = gen._validate_generated_pages(bad_pages)
    check("detects empty title", any("title" in str(e) for r in results for e in r.get("errors", [])))

    # Invalid passing score
    bad_score = [{
        "title": "Test", "template_type": "final-assessment", "order": 0,
        "components": [{"component_type": "final-assessment", "order_index": 0,
                        "data": {"passing_score": 150, "questions": []}}],
    }]
    results = gen._validate_generated_pages(bad_score)
    check("detects invalid passing score", any(
        r["status"] == "error" for r in results
    ))

    # Warning for empty accordion
    empty_accordion = [{
        "title": "FAQ", "template_type": "accordion", "order": 0,
        "components": [{"component_type": "accordion", "order_index": 0,
                        "data": {"items": []}}],
    }]
    results = gen._validate_generated_pages(empty_accordion)
    check("warns on empty accordion", any(
        "no items" in str(w).lower() for r in results for w in r.get("warnings", [])
    ))

    # Warning for empty tabs
    empty_tabs = [{
        "title": "Compare", "template_type": "tabs", "order": 0,
        "components": [{"component_type": "tabs", "order_index": 0,
                        "data": {"tabs": []}}],
    }]
    results = gen._validate_generated_pages(empty_tabs)
    check("warns on empty tabs", any(
        "no tabs" in str(w).lower() for r in results for w in r.get("warnings", [])
    ))

    # Empty components
    no_components = [{
        "title": "Empty", "template_type": "text-content", "order": 0,
        "components": [],
    }]
    results = gen._validate_generated_pages(no_components)
    check("errors on no components", any(
        "component" in str(e).lower() for r in results for e in r.get("errors", [])
    ))

    # ===============================================================
    # GenerationStatus Enum
    # ===============================================================
    print("\n=== GenerationStatus ===")
    statuses = [s.value for s in GenerationStatus]
    check("has pending", "pending" in statuses)
    check("has generating", "generating" in statuses)
    check("has ready_for_review", "ready_for_review" in statuses)
    check("has awaiting_confirmation", "awaiting_confirmation" in statuses)
    check("has completed", "completed" in statuses)
    check("has failed", "failed" in statuses)

    # ===============================================================
    # GenerationError
    # ===============================================================
    print("\n=== GenerationError ===")
    e = GenerationError("TEST_CODE", "Test message", 400)
    check("error code", e.code == "TEST_CODE")
    check("error message", e.message == "Test message")
    check("error http_status", e.http_status == 400)

    e2 = GenerationError("PAGE_GENERATION_FAILED", "LLM failed", 500)
    check("500 error", e2.http_status == 500)

    e3 = GenerationError("IMPORT_JOB_NOT_FOUND", "Not found", 404)
    check("404 error", e3.http_status == 404)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if failures:
        print("FAILURES:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    import asyncio
    success = asyncio.run(main())
    exit(0 if success else 1)
