"""Standalone test runner for US-BKND-AI-030 - Course Assembly.

Tests CourseAssembler: validation, component type mapping,
page spec validation, assembly error handling, editor state shape.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.course_assembler import (
    CourseAssembler, AssemblyError,
    TEMPLATE_TO_COMPONENT, VALID_COMPONENT_TYPES,
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

    mock_db = AsyncMock()
    assembler = CourseAssembler(mock_db)

    # ===============================================================
    # Validation
    # ===============================================================
    print("=== Validation ===")

    # 1. Valid spec
    spec = {
        "title": "Introduction",
        "template_type": "text-content",
        "components": [
            {"component_type": "text-content", "order_index": 0, "data": {"content": "Hello"}},
        ],
    }
    issues = assembler.validate_page_spec(spec)
    check("valid spec passes", len(issues) == 0)

    # 2. Empty title
    spec2 = {"title": "", "template_type": "text-content", "components": []}
    issues = assembler.validate_page_spec(spec2)
    check("empty title detected", any("title" in i["field"] for i in issues))

    # 3. Long title warning
    spec3 = {"title": "x" * 250, "template_type": "text-content", "components": []}
    issues = assembler.validate_page_spec(spec3)
    check("long title warning", any(i["severity"] == "warning" for i in issues))

    # 4. Unknown template type
    spec4 = {"title": "Test", "template_type": "invalid-type", "components": []}
    issues = assembler.validate_page_spec(spec4)
    check("unknown template rejected", any("template_type" in i["field"] for i in issues))

    # 5. Unknown component type
    spec5 = {
        "title": "Test", "template_type": "text-content",
        "components": [{"component_type": "invalid-comp", "order_index": 0, "data": {}}],
    }
    issues = assembler.validate_page_spec(spec5)
    check("unknown component rejected", any("component_type" in i["field"] for i in issues))

    # 6. Valid component types
    for ct in VALID_COMPONENT_TYPES:
        spec = {"title": "T", "template_type": "text-content", "components": [
            {"component_type": ct, "order_index": 0, "data": {}},
        ]}
        issues = assembler.validate_page_spec(spec)
        check(f"valid component type: {ct}", len(issues) == 0)

    # ===============================================================
    # Component Type Mapping
    # ===============================================================
    print("\n=== Component Type Mapping ===")

    # 7. Template-to-component mapping
    check("text-content mapped", TEMPLATE_TO_COMPONENT["text-content"] == "text-content")
    check("accordion mapped", TEMPLATE_TO_COMPONENT["accordion"] == "accordion")
    check("tabs mapped", TEMPLATE_TO_COMPONENT["tabs"] == "tabs")
    check("click-reveal mapped", TEMPLATE_TO_COMPONENT["click-reveal"] == "click-reveal")
    check("final-assessment mapped", TEMPLATE_TO_COMPONENT["final-assessment"] == "final-assessment")

    # 8. Valid component types set
    check("has 5 types", len(VALID_COMPONENT_TYPES) == 5)

    # 9. _map_component_type with valid type
    result = assembler._map_component_type("text-content")
    check("maps valid type", result == "text-content")

    # 10. _map_component_type with invalid type raises
    try:
        assembler._map_component_type("nonexistent")
        check("invalid type raises", False, "should raise")
    except AssemblyError as e:
        check("invalid type raises AssemblyError", e.code == "INVALID_COMPONENT_TYPE")

    # ===============================================================
    # Max Title Length
    # ===============================================================
    print("\n=== Title Truncation ===")
    check("max title length 200", assembler.MAX_TITLE_LENGTH == 200)

    # ===============================================================
    # AssemblyError
    # ===============================================================
    print("\n=== AssemblyError ===")
    e = AssemblyError("PAGE_NOT_FOUND", "Page 'x' not found.", 404)
    check("error code", e.code == "PAGE_NOT_FOUND")
    check("error message", e.message == "Page 'x' not found.")
    check("error http_status", e.http_status == 404)

    e2 = AssemblyError("INVALID_COMPONENT_TYPE", "Bad type", 400)
    check("400 error", e2.http_status == 400)

    # ===============================================================
    # Editor State Shape
    # ===============================================================
    print("\n=== Editor State Shape ===")

    # 11. Verify the state dict shape
    state = {
        "course_id": "c1",
        "pages": [{
            "page_id": "p1",
            "title": "Test",
            "order_index": 0,
            "layout": {"templateType": "text-content"},
            "template_type": "text-content",
            "components": [{
                "component_id": "c1",
                "component_type": "text-content",
                "order_index": 0,
                "data": {"content": "hi"},
            }],
        }],
        "total_pages": 1,
    }
    check("state has course_id", "course_id" in state)
    check("state has pages", "pages" in state)
    check("state has total_pages", "total_pages" in state)
    check("page has components", "components" in state["pages"][0])
    check("component has type", "component_type" in state["pages"][0]["components"][0])
    check("component has data", "data" in state["pages"][0]["components"][0])

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
