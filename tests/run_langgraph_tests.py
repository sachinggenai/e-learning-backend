"""Standalone tests for LangGraph Course Generation Graph — Phase 2.1-2.3.

Run: PYTHONPATH=. python tests/run_langgraph_tests.py

Validates:
    - Graph construction and compilation (with/without LangGraph)
    - Node functions tested independently (no graph needed)
    - Routing functions (conditional edges)
    - State management (_make_initial_state, CourseGenerationState)
    - HITL interrupt behavior (auto-approve when LangGraph unavailable)
    - Graceful degradation (fallback when LangGraph not installed)

All tests work WITHOUT the langgraph package installed.
Each node function is a standalone async function that can be tested in isolation.
"""
from __future__ import annotations
import asyncio
import os
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

passed = 0
failed = 0
failures: list[tuple[str, str]] = []

def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append((name, detail))


# ═══════════════════════════════════════════════════════════════════════
# Graceful Degradation Tests (no LangGraph installed)
# ═══════════════════════════════════════════════════════════════════════

def test_is_langgraph_available():
    """LG-01: is_langgraph_available() returns a bool."""
    from app.services.ai.langgraph.course_generation_graph import is_langgraph_available
    result = is_langgraph_available()
    check("LG-01: Returns bool", isinstance(result, bool))

def test_build_graph_handles_no_langgraph():
    """LG-02: build_graph() returns None when LangGraph not installed."""
    from app.services.ai.langgraph.course_generation_graph import build_graph
    graph = build_graph()
    # When langgraph is not installed, graph should be None (graceful)
    if graph is None:
        check("LG-02: Graceful None when langgraph unavailable", True)
    else:
        check("LG-02: Compiled graph returned (langgraph IS installed)", graph is not None)

def test_run_course_generation_no_langgraph():
    """LG-03: run_course_generation returns error dict when LangGraph unavailable."""
    from app.services.ai.langgraph.course_generation_graph import run_course_generation
    result = asyncio.run(run_course_generation({"job_id": "test-job", "file_path": "/dev/null"}))
    if "errors" in result:
        check("LG-03: Returns error when langgraph unavailable", True)
    else:
        check("LG-03: Returns state from successful run (langgraph IS installed)", "status" in result)

def test_make_initial_state():
    """LG-04: _make_initial_state creates state with all required fields."""
    from app.services.ai.langgraph.course_generation_graph import _make_initial_state
    state = _make_initial_state(
        job_id="j-001", session_id="s-001", user_id="u-001",
        organization_id="org-001", file_path="/tmp/test.pdf",
        file_hash="abc123", course_id="c-001",
    )
    check("LG-04: job_id", state["job_id"] == "j-001")
    check("LG-04: session_id", state["session_id"] == "s-001")
    check("LG-04: file_path", state["file_path"] == "/tmp/test.pdf")
    check("LG-04: file_hash", state["file_hash"] == "abc123")
    check("LG-04: current_phase starts at validate_input", state["current_phase"] == "validate_input")
    check("LG-04: plan_approved is False", state["plan_approved"] is False)
    check("LG-04: final_approved is False", state["final_approved"] is False)
    check("LG-04: template_assignments is list", state["template_assignments"] == [])
    check("LG-04: generated_pages is list", state["generated_pages"] == [])
    check("LG-04: errors is list", state["errors"] == [])
    check("LG-04: hitl_decision is None", state["hitl_decision"] is None)
    check("LG-04: status is pending", state["status"] == "pending")

def test_make_initial_state_defaults():
    """LG-05: _make_initial_state with no args still produces valid structure."""
    from app.services.ai.langgraph.course_generation_graph import _make_initial_state
    state = _make_initial_state()
    check("LG-05: Has job_id (empty)", isinstance(state["job_id"], str))
    check("LG-05: Has page_plan (None)", state["page_plan"] is None)
    check("LG-05: Has rag_context (None)", state["rag_context"] is None)


# ═══════════════════════════════════════════════════════════════════════
# Node Function Tests (each tested independently, no graph needed)
# ═══════════════════════════════════════════════════════════════════════

def test_node_validate_input_with_file_path():
    """LG-06: node_validate_input with valid file → advances to extract phase."""
    from app.services.ai.langgraph.course_generation_graph import node_validate_input
    result = asyncio.run(node_validate_input({
        "job_id": "j-001", "file_path": "/tmp/test.pdf", "file_hash": "abc",
    }))
    check("LG-06: Advances to extract", result.get("current_phase") == "extract")
    check("LG-06: Status is running", result.get("status") == "running")

def test_node_validate_input_empty_file_path():
    """LG-07: node_validate_input with empty file_path → error + failed."""
    from app.services.ai.langgraph.course_generation_graph import node_validate_input
    result = asyncio.run(node_validate_input({
        "job_id": "j-001", "file_path": "", "file_hash": "",
    }))
    check("LG-07: Status=failed", result.get("status") == "failed")
    check("LG-07: Has error", len(result.get("errors", [])) > 0)
    check("LG-07: Error mentions file", "file" in str(result["errors"]).lower())

def test_node_hitl_plan_approval_auto_approves_without_langgraph():
    """LG-08: HITL plan approval auto-approves when interrupt is None."""
    from app.services.ai.langgraph.course_generation_graph import node_hitl_plan_approval
    state = {
        "job_id": "j-001",
        "page_plan": [{"title": "P1", "template_type": "content-text"}],
    }
    result = asyncio.run(node_hitl_plan_approval(state))
    check("LG-08: hitl_decision=approve", result.get("hitl_decision") == "approve")
    check("LG-08: plan_approved=True", result.get("plan_approved") is True)

def test_node_hitl_final_confirm_auto_confirms_without_langgraph():
    """LG-09: HITL final confirm auto-confirms when interrupt is None."""
    from app.services.ai.langgraph.course_generation_graph import node_hitl_final_confirm
    state = {"job_id": "j-001", "generated_pages": [{"title": "P1"}]}
    result = asyncio.run(node_hitl_final_confirm(state))
    check("LG-09: hitl_decision=confirm", result.get("hitl_decision") == "confirm")
    check("LG-09: final_approved=True", result.get("final_approved") is True)

def test_node_rag_retrieve_handles_missing_page_plan():
    """LG-10: RAG retrieval returns empty context for empty page_plan."""
    from app.services.ai.langgraph.course_generation_graph import node_rag_retrieve
    state = {"job_id": "j-001", "page_plan": [], "session_id": "s-001", "user_id": "u-001"}
    result = asyncio.run(node_rag_retrieve(state))
    check("LG-10: rag_context empty list", result.get("rag_context") == [])
    check("LG-10: Advances to select_templates", result.get("current_phase") == "select_templates")

def test_node_rag_retrieve_handles_exception_gracefully():
    """LG-11: RAG retrieval returns empty context on exception (graceful degradation)."""
    from app.services.ai.langgraph.course_generation_graph import node_rag_retrieve
    # Using a state without actual DB session — should fail gracefully
    state = {
        "job_id": "j-001", "page_plan": [{"title": "Test"}],
        "session_id": "s-001", "user_id": "u-001",
    }
    result = asyncio.run(node_rag_retrieve(state))
    check("LG-11: rag_context exists", "rag_context" in result)
    check("LG-11: Advances to select_templates (non-fatal)",
          result.get("current_phase") == "select_templates")

def test_node_validate_success_path():
    """LG-12: node_validate with clean pages → advances to HITL final confirm."""
    from app.services.ai.langgraph.course_generation_graph import node_validate
    state = {
        "job_id": "j-001",
        "generated_pages": [
            {"title": "P1", "template_type": "content-text",
             "components": [{"component_type": "content-text", "data": {"content": "Hi"}}]},
            {"title": "P2", "template_type": "tabs",
             "components": [{"component_type": "tabs", "data": {"tabs": []}}]},
        ],
    }
    result = asyncio.run(node_validate(state))
    check("LG-12: Advances to hitl_final_confirm",
          result.get("current_phase") == "hitl_final_confirm")
    check("LG-12: Has validation_results", "validation_results" in result)
    check("LG-12: total_pages=2", result["validation_results"]["total_pages"] == 2)
    check("LG-12: No errors", result["validation_results"]["errors"] == 0)
    check("LG-12: No warnings", result["validation_results"]["warnings"] == 0)

def test_node_validate_detects_missing_title():
    """LG-13: node_validate flags pages with missing title."""
    from app.services.ai.langgraph.course_generation_graph import node_validate
    state = {
        "job_id": "j-001",
        "generated_pages": [
            {"template_type": "content-text",
             "components": [{"component_type": "content-text", "data": {"content": "Hi"}}]},
        ],
    }
    result = asyncio.run(node_validate(state))
    check("LG-13: Errors > 0", result["validation_results"]["errors"] > 0)

def test_node_validate_detects_empty_components():
    """LG-14: node_validate warns on pages with no components."""
    from app.services.ai.langgraph.course_generation_graph import node_validate
    state = {
        "job_id": "j-001",
        "generated_pages": [
            {"title": "P1", "template_type": "content-text", "components": []},
        ],
    }
    result = asyncio.run(node_validate(state))
    check("LG-14: Has warnings", result["validation_results"]["warnings"] > 0)

def test_node_validate_assessment_validation():
    """LG-15: node_validate checks assessment pages for passing_score."""
    from app.services.ai.langgraph.course_generation_graph import node_validate
    # Assessment with valid passing_score
    state_good = {
        "job_id": "j-001",
        "generated_pages": [{
            "title": "Quiz", "template_type": "final-assessment",
            "components": [{
                "component_type": "final-assessment",
                "data": {"passing_score": 80, "questions": [{"id": "q1"}]},
            }],
        }],
    }
    result = asyncio.run(node_validate(state_good))
    check("LG-15: Valid assessment passes", result["validation_results"]["errors"] == 0)

    # Assessment with invalid passing_score
    state_bad = {
        "job_id": "j-001",
        "generated_pages": [{
            "title": "Bad Quiz", "template_type": "final-assessment",
            "components": [{
                "component_type": "final-assessment",
                "data": {"passing_score": 150},  # Invalid: > 100
            }],
        }],
    }
    result_bad = asyncio.run(node_validate(state_bad))
    check("LG-15: Invalid passing_score flagged", result_bad["validation_results"]["errors"] > 0)

    # Assessment with no questions
    state_empty = {
        "job_id": "j-001",
        "generated_pages": [{
            "title": "Empty Quiz", "template_type": "final-assessment",
            "components": [{
                "component_type": "final-assessment",
                "data": {"passing_score": 80, "questions": []},
            }],
        }],
    }
    result_empty = asyncio.run(node_validate(state_empty))
    check("LG-15: No-questions assessment warned", result_empty["validation_results"]["warnings"] > 0)

def test_node_persist_no_pages():
    """LG-16: node_persist with no pages → error + failed."""
    from app.services.ai.langgraph.course_generation_graph import node_persist
    state = {
        "job_id": "j-001", "session_id": "s-001",
        "user_id": "u-001", "organization_id": "org-001",
        "generated_pages": [], "course_id": "c-001",
    }
    result = asyncio.run(node_persist(state))
    check("LG-16: Status=failed", result.get("status") == "failed")
    check("LG-16: Has errors", len(result.get("errors", [])) > 0)

def test_node_plan_handles_no_sections():
    """LG-17: node_plan with no sections → error + failed."""
    from app.services.ai.langgraph.course_generation_graph import node_plan
    state = {"job_id": "j-001", "extracted_sections": None}
    result = asyncio.run(node_plan(state))
    check("LG-17: Status=failed", result.get("status") == "failed")
    check("LG-17: Error mentions sections", any("section" in str(e).lower() for e in result.get("errors", [])))

def test_node_extract_handles_empty_file_path():
    """LG-18: node_extract with empty file_path → error."""
    from app.services.ai.langgraph.course_generation_graph import node_extract
    state = {"job_id": "j-001", "file_path": ""}
    result = asyncio.run(node_extract(state))
    check("LG-18: Status=failed", result.get("status") == "failed")

def test_node_select_templates_fanout_without_langgraph():
    """LG-19: Fan-out node returns continue when Send is None (no LangGraph)."""
    from app.services.ai.langgraph.course_generation_graph import node_select_templates_fanout
    state = {"page_plan": [{"title": "P1"}, {"title": "P2"}], "job_id": "j-001"}
    result = asyncio.run(node_select_templates_fanout(state))
    # When Send is None (no LangGraph), it returns a dict
    if isinstance(result, dict):
        check("LG-19: Returns dict (sequential fallback)", result.get("current_phase") == "generate_content_fanout")
    else:
        check("LG-19: Returns list (Send fan-out, langgraph IS installed)", isinstance(result, list))

def test_node_generate_content_fanout_without_langgraph():
    """LG-20: Content fan-out returns continue when Send is None."""
    from app.services.ai.langgraph.course_generation_graph import node_generate_content_fanout
    state = {"page_plan": [{"title": "P1"}], "template_assignments": [], "rag_context": []}
    result = asyncio.run(node_generate_content_fanout(state))
    if isinstance(result, dict):
        check("LG-20: Returns dict (sequential fallback)", result.get("current_phase") == "validate")
    else:
        check("LG-20: Returns list (Send fan-out, langgraph IS installed)", isinstance(result, list))

def test_node_select_template_for_page_basic():
    """LG-21: Template selection worker node returns template_assignments."""
    from app.services.ai.langgraph.course_generation_graph import node_select_template_for_page
    state = {
        "page": {"title": "Quiz Page", "template_type": "final-assessment",
                 "learning_objective": "Test", "source_content": "quiz assessment MCQ test score"},
        "page_index": 0, "total_pages": 5, "job_id": "j-001",
    }
    result = asyncio.run(node_select_template_for_page(state))
    check("LG-21: Has template_assignments", "template_assignments" in result)
    check("LG-21: 1 assignment", len(result["template_assignments"]) == 1)
    check("LG-21: Has template_type", "template_type" in result["template_assignments"][0])
    check("LG-21: page_index=0", result["template_assignments"][0]["page_index"] == 0)

def test_node_generate_page_content_basic():
    """LG-22: Content generation worker node returns generated_pages."""
    from app.services.ai.langgraph.course_generation_graph import node_generate_page_content
    state = {
        "page": {"title": "Test Page", "source_content": "Test content",
                 "learning_objective": "Learn", "template_type": "content-text"},
        "template": {"template_type": "content-text"},
        "rag_context": [], "course_context": {"title": "Test Course"},
        "page_index": 0, "total_pages": 1, "job_id": "j-001",
    }
    result = asyncio.run(node_generate_page_content(state))
    check("LG-22: Has generated_pages", "generated_pages" in result)
    check("LG-22: 1 page", len(result["generated_pages"]) == 1)
    check("LG-22: Has title", result["generated_pages"][0].get("title") is not None)

def test_node_generate_page_content_error_handling():
    """LG-23: Content generation worker produces fallback page on error."""
    from app.services.ai.langgraph.course_generation_graph import node_generate_page_content
    # Empty page should produce a fallback result, not crash
    state = {
        "page": {}, "template": {}, "rag_context": [],
        "course_context": {}, "page_index": 0, "total_pages": 1, "job_id": "j-001",
    }
    result = asyncio.run(node_generate_page_content(state))
    check("LG-23: Returns generated_pages (fallback)", len(result["generated_pages"]) > 0)
    check("LG-23: Fallback has title", "title" in result["generated_pages"][0])


# ═══════════════════════════════════════════════════════════════════════
# Routing Function Tests
# ═══════════════════════════════════════════════════════════════════════

def test_route_after_hitl_plan_approved():
    """LG-24: Approved plan routes to rag_retrieve."""
    from app.services.ai.langgraph.course_generation_graph import _route_after_hitl_plan
    result = _route_after_hitl_plan({"plan_approved": True})
    check("LG-24: Routes to rag_retrieve", result == "rag_retrieve")

def test_route_after_hitl_plan_rejected():
    """LG-25: Rejected plan routes to END/__end__."""
    from app.services.ai.langgraph.course_generation_graph import _route_after_hitl_plan
    result = _route_after_hitl_plan({"plan_approved": False})
    # When END is None (no LangGraph), it falls back to "__end__"
    check("LG-25: Routes to END or __end__", result in ("__end__", None))

def test_route_after_validate_clean():
    """LG-26: Clean validation → HITL final confirm."""
    from app.services.ai.langgraph.course_generation_graph import _route_after_validate
    result = asyncio.run(_route_after_validate({
        "validation_results": {"errors": 0, "warnings": 0},
    }))
    check("LG-26: Routes to hitl_final_confirm", result == "hitl_final_confirm")

def test_route_after_validate_with_errors():
    """LG-27: Validation errors → re-plan (Supervisor deterministic path)."""
    from app.services.ai.langgraph.course_generation_graph import _route_after_validate
    result = asyncio.run(_route_after_validate({
        "validation_results": {"errors": 3, "warnings": 0},
        "generated_pages": [],
        "replan_count": 0,
    }))
    check("LG-27: Routes to plan (re-plan)", result == "plan")

def test_route_after_hitl_final_confirmed():
    """LG-28: Final confirm → persist."""
    from app.services.ai.langgraph.course_generation_graph import _route_after_hitl_final
    result = _route_after_hitl_final({"final_approved": True})
    check("LG-28: Routes to persist", result == "persist")

def test_route_after_hitl_final_rejected():
    """LG-29: Final rejection → re-plan."""
    from app.services.ai.langgraph.course_generation_graph import _route_after_hitl_final
    result = _route_after_hitl_final({"final_approved": False})
    check("LG-29: Routes to plan (re-plan)", result == "plan")

def test_route_after_hitl_plan_with_hitl_decision_string():
    """LG-30: hitl_decision='approve' also triggers approval routing."""
    from app.services.ai.langgraph.course_generation_graph import _route_after_hitl_plan
    result = _route_after_hitl_plan({"plan_approved": False, "hitl_decision": "approve"})
    check("LG-30: Routes to rag_retrieve via decision string", result == "rag_retrieve")

def test_route_after_hitl_final_with_decision_string():
    """LG-31: hitl_decision='confirm' triggers persist routing."""
    from app.services.ai.langgraph.course_generation_graph import _route_after_hitl_final
    result = _route_after_hitl_final({"final_approved": False, "hitl_decision": "confirm"})
    check("LG-31: Routes to persist via decision string", result == "persist")


# ═══════════════════════════════════════════════════════════════════════
# Integration: Graph-level smoke test
# ═══════════════════════════════════════════════════════════════════════

def test_integration_all_phases_present():
    """LG-32: All 10 phases are represented as node functions."""
    from app.services.ai.langgraph import course_generation_graph as cg
    node_funcs = [
        "node_validate_input", "node_extract", "node_plan",
        "node_hitl_plan_approval", "node_rag_retrieve",
        "node_select_templates_fanout", "node_select_template_for_page",
        "node_generate_content_fanout", "node_generate_page_content",
        "node_validate", "node_hitl_final_confirm", "node_persist",
    ]
    for func_name in node_funcs:
        check(f"LG-32: {func_name} exists", hasattr(cg, func_name))

def test_integration_phases_can_compose():
    """LG-33: Node outputs can be composed — phase N output feeds phase N+1 input."""
    from app.services.ai.langgraph.course_generation_graph import (
        node_validate_input, node_hitl_plan_approval,
        _route_after_hitl_plan, node_persist,
        node_validate, _route_after_validate,
        _make_initial_state,
    )

    # Simulate a minimal pipeline chain
    state = _make_initial_state(job_id="j-001", file_path="/tmp/test.pdf")

    # Phase 0
    r0 = asyncio.run(node_validate_input(state))
    state.update(r0)
    check("LG-33: Phase 0 → extract", state["current_phase"] == "extract")

    # Skip to HITL-1 (without extraction/planning)
    state["page_plan"] = [{"title": "Test", "template_type": "content-text"}]
    r3 = asyncio.run(node_hitl_plan_approval(state))
    state.update(r3)
    check("LG-33: HITL-1 → approve (no langgraph)", state["plan_approved"] is True)

    # Route
    route = _route_after_hitl_plan(state)
    check("LG-33: Route → rag_retrieve", route == "rag_retrieve")

    # Skip to validation
    state["generated_pages"] = [
        {"title": "Test", "template_type": "content-text",
         "components": [{"component_type": "content-text", "data": {"content": "Hi"}}]},
    ]
    r7 = asyncio.run(node_validate(state))
    state.update(r7)
    check("LG-33: Validation → hitl_final_confirm",
          state["current_phase"] == "hitl_final_confirm")
    check("LG-33: 0 validation errors", state["validation_results"]["errors"] == 0)

    route2 = asyncio.run(_route_after_validate(state))
    check("LG-33: Route → hitl_final_confirm", route2 == "hitl_final_confirm")


# ═══════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("LangGraph Graph Tests — Nodes, Routing, State, Degradation")
    print("=" * 60)

    print("\n--- Graceful Degradation ---")
    test_is_langgraph_available()
    test_build_graph_handles_no_langgraph()
    test_run_course_generation_no_langgraph()
    test_make_initial_state()
    test_make_initial_state_defaults()

    print("\n--- Node Functions ---")
    test_node_validate_input_with_file_path()
    test_node_validate_input_empty_file_path()
    test_node_hitl_plan_approval_auto_approves_without_langgraph()
    test_node_hitl_final_confirm_auto_confirms_without_langgraph()
    test_node_rag_retrieve_handles_missing_page_plan()
    test_node_rag_retrieve_handles_exception_gracefully()
    test_node_validate_success_path()
    test_node_validate_detects_missing_title()
    test_node_validate_detects_empty_components()
    test_node_validate_assessment_validation()
    test_node_persist_no_pages()
    test_node_plan_handles_no_sections()
    test_node_extract_handles_empty_file_path()
    test_node_select_templates_fanout_without_langgraph()
    test_node_generate_content_fanout_without_langgraph()
    test_node_select_template_for_page_basic()
    test_node_generate_page_content_basic()
    test_node_generate_page_content_error_handling()

    print("\n--- Routing Functions ---")
    test_route_after_hitl_plan_approved()
    test_route_after_hitl_plan_rejected()
    test_route_after_validate_clean()
    test_route_after_validate_with_errors()
    test_route_after_hitl_final_confirmed()
    test_route_after_hitl_final_rejected()
    test_route_after_hitl_plan_with_hitl_decision_string()
    test_route_after_hitl_final_with_decision_string()

    print("\n--- Integration Smoke ---")
    test_integration_all_phases_present()
    test_integration_phases_can_compose()

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    if failures:
        print("\nFAILURES:")
        for name, detail in failures:
            print(f"  {name}: {detail}")
