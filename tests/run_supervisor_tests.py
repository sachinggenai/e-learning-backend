"""Standalone test runner for SupervisorRouter — Phase 2.6 (FIX-5).

Run: PYTHONPATH=. python tests/run_supervisor_tests.py

Validates:
    SupervisorRouter deterministic rules (~90% coverage cases)
    LLM-based decision fallback (graceful degradation)
    Route constant correctness
    Edge cases (budget exhaustion, max replans, etc.)
"""
from __future__ import annotations
import asyncio
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.langgraph.supervisor import (
    SupervisorRouter,
    ROUTE_REPLAN,
    ROUTE_SKIP,
    ROUTE_ABORT,
    ROUTE_RETRY,
    SUPERVISOR_SYSTEM_PROMPT,
)

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


# ═══════════════════════════════════════════════════════════════════
# CATEGORY A: Route Constants
# ═══════════════════════════════════════════════════════════════════

def test_route_constants_defined():
    """SUP-01: All 4 route constants have expected values."""
    check("SUP-01a: ROUTE_REPLAN == 'plan'", ROUTE_REPLAN == "plan")
    check("SUP-01b: ROUTE_SKIP == 'skip_and_continue'", ROUTE_SKIP == "skip_and_continue")
    check("SUP-01c: ROUTE_ABORT == '__end__'", ROUTE_ABORT == "__end__")
    check("SUP-01d: ROUTE_RETRY == 'retry_current'", ROUTE_RETRY == "retry_current")


def test_system_prompt_not_empty():
    """SUP-02: Supervisor system prompt is defined and non-empty."""
    check("SUP-02a: SUPERVISOR_SYSTEM_PROMPT defined",
          SUPERVISOR_SYSTEM_PROMPT is not None)
    check("SUP-02b: SUPERVISOR_SYSTEM_PROMPT > 100 chars",
          len(SUPERVISOR_SYSTEM_PROMPT) > 100)
    check("SUP-02c: mentions 'replan'", "replan" in SUPERVISOR_SYSTEM_PROMPT)
    check("SUP-02d: mentions 'abort'", "abort" in SUPERVISOR_SYSTEM_PROMPT)


# ═══════════════════════════════════════════════════════════════════
# CATEGORY B: Deterministic Rules
# ═══════════════════════════════════════════════════════════════════

async def test_supervisor_zero_errors_skip():
    """SUP-03: Zero errors → skip_and_continue (no LLM call)."""
    router = SupervisorRouter()
    result = await router.decide("validate", error_count=0)
    check("SUP-03: zero errors → skip", result == ROUTE_SKIP)


async def test_supervisor_abort_after_3_replans():
    """SUP-04: 3+ previous replans → abort (infinite loop guard)."""
    router = SupervisorRouter()
    result = await router.decide("validate", error_count=3, previous_route_count=3)
    check("SUP-04: 3 replans → abort", result == ROUTE_ABORT)

    result2 = await router.decide("validate", error_count=1, previous_route_count=4)
    check("SUP-04b: 4 replans → abort", result2 == ROUTE_ABORT)


async def test_supervisor_abort_budget_exhausted():
    """SUP-05: Budget < $0.05 with errors → abort."""
    router = SupervisorRouter()
    result = await router.decide("validate", error_count=1, budget_remaining=0.01)
    check("SUP-05a: budget $0.01 → abort", result == ROUTE_ABORT)

    result2 = await router.decide("validate", error_count=5, budget_remaining=0.04)
    check("SUP-05b: budget $0.04 → abort", result2 == ROUTE_ABORT)


async def test_supervisor_minor_errors_skip():
    """SUP-06: ≤2 errors AND >5 pages → skip (minor issues)."""
    router = SupervisorRouter()
    result = await router.decide("validate", error_count=2, total_pages=10)
    check("SUP-06a: 2 errors, 10 pages → skip", result == ROUTE_SKIP)

    result2 = await router.decide("validate", error_count=1, total_pages=6)
    check("SUP-06b: 1 error, 6 pages → skip", result2 == ROUTE_SKIP)


async def test_supervisor_many_errors_replan():
    """SUP-07: >2 errors, <2 replans, no LLM client → replan (deterministic fallback)."""
    router = SupervisorRouter()  # No LLM client
    result = await router.decide("validate", error_count=4, previous_route_count=0)
    check("SUP-07a: 4 errors → replan", result == ROUTE_REPLAN)

    result2 = await router.decide("validate", error_count=3, previous_route_count=1)
    check("SUP-07b: 3 errors, 1 replan → replan", result2 == ROUTE_REPLAN)


async def test_supervisor_many_errors_abort():
    """SUP-08: >5 errors → abort (deterministic fallback)."""
    router = SupervisorRouter()
    result = await router.decide("validate", error_count=6, previous_route_count=0)
    check("SUP-08a: 6 errors → abort", result == ROUTE_ABORT)

    result2 = await router.decide("validate", error_count=10, previous_route_count=0)
    check("SUP-08b: 10 errors → abort", result2 == ROUTE_ABORT)


async def test_supervisor_fallback_skip_default():
    """SUP-09: 1-2 errors, ≤5 pages → skip (fallback default)."""
    router = SupervisorRouter()
    result = await router.decide("validate", error_count=1, total_pages=3)
    check("SUP-09a: 1 error, 3 pages → skip", result == ROUTE_SKIP)

    result2 = await router.decide("validate", error_count=2, total_pages=5)
    check("SUP-09b: 2 errors, 5 pages → skip", result2 == ROUTE_SKIP)


# ═══════════════════════════════════════════════════════════════════
# CATEGORY C: LLM-Based Decision & Fallback
# ═══════════════════════════════════════════════════════════════════

async def test_supervisor_llm_client_triggers_llm_path():
    """SUP-10: With LLM client and <2 replans, _llm_decide is attempted."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = '{"action": "replan", "reasoning": "test decision"}'
    mock_llm.chat.return_value = mock_response

    router = SupervisorRouter(llm_client=mock_llm)
    result = await router.decide("validate", error_count=3, total_pages=1, previous_route_count=0)
    check("SUP-10a: LLM returned replan", result == ROUTE_REPLAN)
    check("SUP-10b: LLM chat was called", mock_llm.chat.called)


async def test_supervisor_llm_unavailable_falls_back():
    """SUP-11: LLM client raises → deterministic fallback, no crash."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(side_effect=Exception("LLM unavailable"))

    router = SupervisorRouter(llm_client=mock_llm)
    result = await router.decide("validate", error_count=3, total_pages=1, previous_route_count=0)
    check("SUP-11a: decision returned despite LLM failure", result is not None)
    check("SUP-11b: fallback to replan", result == ROUTE_REPLAN)


async def test_supervisor_llm_returns_invalid_json():
    """SUP-12: LLM returns non-JSON → fallback to skip (safe default)."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "not valid json at all"
    mock_llm.chat.return_value = mock_response

    router = SupervisorRouter(llm_client=mock_llm)
    result = await router.decide("validate", error_count=3, total_pages=1, previous_route_count=0)
    check("SUP-12: invalid JSON → returns skip", result == ROUTE_SKIP)


async def test_supervisor_llm_json_with_markdown_block():
    """SUP-13: LLM response wrapped in ```json block is parsed correctly."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = '```json\n{"action": "abort", "reasoning": "too many issues"}\n```'
    mock_llm.chat.return_value = mock_response

    router = SupervisorRouter(llm_client=mock_llm)
    result = await router.decide("validate", error_count=3, total_pages=1, previous_route_count=0)
    check("SUP-13a: markdown block parsed", result == ROUTE_ABORT)


async def test_supervisor_llm_retry_action():
    """SUP-14: LLM can return 'retry' action mapped to ROUTE_RETRY."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = '{"action": "retry", "reasoning": "transient error"}'
    mock_llm.chat.return_value = mock_response

    router = SupervisorRouter(llm_client=mock_llm)
    result = await router.decide("validate", error_count=3, total_pages=1, previous_route_count=0)
    check("SUP-14: retry action mapped", result == ROUTE_RETRY)


# ═══════════════════════════════════════════════════════════════════
# CATEGORY D: Initialization & Robustness
# ═══════════════════════════════════════════════════════════════════

async def test_supervisor_init_without_llm():
    """SUP-15: SupervisorRouter works without LLM client (deterministic only)."""
    router = SupervisorRouter()
    check("SUP-15a: _llm_client is None", router._llm_client is None)
    result = await router.decide("validate", error_count=0)
    check("SUP-15b: works without LLM", result == ROUTE_SKIP)


def test_supervisor_init_attempts_model_tier_router():
    """SUP-16: Constructor attempts to load ModelTierRouter (non-fatal on failure)."""
    with patch("app.services.ai.langgraph.supervisor.logger", MagicMock()):
        router = SupervisorRouter()
        check("SUP-16: constructor completes without error", router is not None)


# ═══════════════════════════════════════════════════════════════════
# CATEGORY E: Review Phase Routing
# ═══════════════════════════════════════════════════════════════════

async def test_supervisor_review_phase_decision():
    """SUP-17: Supervisor works for plan-phase (not just validate)."""
    router = SupervisorRouter()
    result = await router.decide("plan", error_count=4, previous_route_count=0)
    check("SUP-17: plan phase with errors → replan", result == ROUTE_REPLAN)


async def test_supervisor_decision_always_returns_valid_route():
    """SUP-18: Every decision returns one of the 4 valid route constants."""
    router = SupervisorRouter()
    valid_routes = {ROUTE_REPLAN, ROUTE_SKIP, ROUTE_ABORT, ROUTE_RETRY}

    test_cases = [
        {"error_count": 0, "previous_route_count": 0, "total_pages": 0, "budget_remaining": 999},
        {"error_count": 1, "previous_route_count": 0, "total_pages": 3, "budget_remaining": 999},
        {"error_count": 2, "previous_route_count": 1, "total_pages": 10, "budget_remaining": 0.50},
        {"error_count": 3, "previous_route_count": 0, "total_pages": 2, "budget_remaining": 999},
        {"error_count": 6, "previous_route_count": 0, "total_pages": 20, "budget_remaining": 999},
        {"error_count": 1, "previous_route_count": 3, "total_pages": 5, "budget_remaining": 999},
        {"error_count": 1, "previous_route_count": 0, "total_pages": 10, "budget_remaining": 0.01},
    ]
    for i, tc in enumerate(test_cases):
        result = await router.decide("validate", **tc)
        check(f"SUP-18-{i}: valid route returned ({result})", result in valid_routes,
              f"Got {result}, expected one of {valid_routes}")


# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

async def run_all_tests():
    print("=" * 60)
    print("SupervisorRouter — Phase 2.6 Tests (FIX-5)")
    print("=" * 60)

    print("\n--- A: Route Constants ---")
    test_route_constants_defined()
    test_system_prompt_not_empty()

    print("\n--- B: Deterministic Rules ---")
    await test_supervisor_zero_errors_skip()
    await test_supervisor_abort_after_3_replans()
    await test_supervisor_abort_budget_exhausted()
    await test_supervisor_minor_errors_skip()
    await test_supervisor_many_errors_replan()
    await test_supervisor_many_errors_abort()
    await test_supervisor_fallback_skip_default()

    print("\n--- C: LLM-Based Decision & Fallback ---")
    await test_supervisor_llm_client_triggers_llm_path()
    await test_supervisor_llm_unavailable_falls_back()
    await test_supervisor_llm_returns_invalid_json()
    await test_supervisor_llm_json_with_markdown_block()
    await test_supervisor_llm_retry_action()

    print("\n--- D: Initialization & Robustness ---")
    await test_supervisor_init_without_llm()
    test_supervisor_init_attempts_model_tier_router()

    print("\n--- E: Review Phase Routing ---")
    await test_supervisor_review_phase_decision()
    await test_supervisor_decision_always_returns_valid_route()

    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed ({total} total)")
    print(f"{'=' * 60}")
    if failures:
        for name, detail in failures:
            print(f"  FAIL: {name}")
            if detail:
                print(f"        {detail}")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
