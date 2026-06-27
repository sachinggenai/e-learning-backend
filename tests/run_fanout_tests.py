"""Standalone tests for Redis Streams Fan-Out Manager — Phase 1.1.

Run: PYTHONPATH=. python tests/run_fanout_tests.py

Validates:
    - StreamManager sequential fallback (Redis unavailable path)
    - PageResult and FanOutResult dataclasses
    - Fan-out with N concurrent workers via asyncio.gather
    - Partial failure handling and result ordering
    - Progress tracking
    - Redis availability detection

All tests work without Redis. The sequential fallback is the production
degradation path and is tested thoroughly.
"""
from __future__ import annotations
import asyncio
import json as _json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

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
# Dataclass Tests
# ═══════════════════════════════════════════════════════════════════════

def test_page_message_dataclass():
    """FAN-01: PageMessage dataclass importable and constructable."""
    from app.services.ai.fanout import PageMessage
    msg = PageMessage(
        page_index=0, total_pages=5,
        page_plan={"title": "Test"}, template_assignment={"template_type": "content-text"},
        rag_context=[], course_context={"title": "Course"},
    )
    check("FAN-01: page_index", msg.page_index == 0)
    check("FAN-01: total_pages", msg.total_pages == 5)

def test_page_result_dataclass():
    """FAN-02: PageResult dataclass with status enum."""
    from app.services.ai.fanout import PageResult
    r_ok = PageResult(page_index=0, status="success", data={"title": "OK"}, duration_ms=100.0)
    r_err = PageResult(page_index=1, status="error", error="Something broke")
    check("FAN-02: success status", r_ok.status == "success")
    check("FAN-02: error status", r_err.status == "error")
    check("FAN-02: error message", r_err.error == "Something broke")
    check("FAN-02: duration tracked", r_ok.duration_ms == 100.0)
    check("FAN-02: retry_count default", r_ok.retry_count == 0)

def test_fanout_result_dataclass():
    """FAN-03: FanOutResult aggregates PageResults."""
    from app.services.ai.fanout import FanOutResult, PageResult
    result = FanOutResult(
        job_id="job-123",
        status="partial",
        pages=[
            PageResult(page_index=0, status="success", data={"title": "A"}),
            PageResult(page_index=1, status="error", error="Failed"),
        ],
        total_duration_ms=5000.0,
        backend="sequential",
    )
    check("FAN-03: Status partial", result.status == "partial")
    check("FAN-03: 2 pages", len(result.pages) == 2)
    check("FAN-03: Backend", result.backend == "sequential")
    check("FAN-03: Duration", result.total_duration_ms == 5000.0)


# ═══════════════════════════════════════════════════════════════════════
# StreamManager — Sequential Fallback (the critical degradation path)
# ═══════════════════════════════════════════════════════════════════════

# A deterministic test generate function that returns predictable results
async def _mock_generate(page_plan, template_assignment, rag_context,
                         course_context, page_index, total_pages):
    """Simulate a ContentGeneratorAgent.generate_page() call."""
    await asyncio.sleep(0.001)  # Simulate minimal async work
    return {
        "title": page_plan.get("title", f"Page {page_index}"),
        "template_type": template_assignment.get("template_type", "content-text"),
        "order": page_index,
        "components": [{"component_type": "test", "data": {"page_index": page_index}}],
    }

async def _mock_generate_with_failure(page_plan, template_assignment, rag_context,
                                      course_context, page_index, total_pages):
    """Simulate generation that fails for specific pages."""
    if page_index == 1:  # Fail page 1
        raise RuntimeError(f"Simulated failure for page {page_index}")
    return await _mock_generate(page_plan, template_assignment, rag_context,
                                course_context, page_index, total_pages)

def test_stream_manager_import():
    """FAN-04: StreamManager class importable."""
    from app.services.ai.fanout import StreamManager
    check("FAN-04: StreamManager exists", StreamManager is not None)
    check("FAN-04: Has fan_out_pages", hasattr(StreamManager, 'fan_out_pages'))
    check("FAN-04: Has get_stream_progress", hasattr(StreamManager, 'get_stream_progress'))

def test_stream_manager_sequential_basic():
    """FAN-05: Sequential fallback generates N pages with correct ordering."""
    from app.services.ai.fanout import StreamManager
    manager = StreamManager(max_concurrency=3)

    pages = [{"title": f"Page {i}"} for i in range(5)]
    templates = [{"template_type": "content-text"} for _ in range(5)]

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-job-001",
        pages=pages, templates=templates,
        rag_context=[], course_context={"title": "Test Course"},
        generate_func=_mock_generate,
    ))
    check("FAN-05: Status success", result.status == "success")
    check("FAN-05: 5 pages generated", len(result.pages) == 5)
    check("FAN-05: Backend is redis or sequential", result.backend in ("redis", "sequential"))
    check("FAN-05: All pages success", all(p.status == "success" for p in result.pages))
    # Verify ordering is preserved
    for i, page_result in enumerate(result.pages):
        check(f"FAN-05: Page {i} has correct index", page_result.page_index == i)

def test_stream_manager_sequential_with_failures():
    """FAN-06: Partial failure produces partial status with error pages."""
    from app.services.ai.fanout import StreamManager
    manager = StreamManager(max_concurrency=3)

    pages = [{"title": f"Page {i}"} for i in range(4)]
    templates = [{"template_type": "content-text"} for _ in range(4)]

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-job-002",
        pages=pages, templates=templates,
        rag_context=[], course_context={"title": "Test"},
        generate_func=_mock_generate_with_failure,
    ))
    check("FAN-06: Status partial", result.status == "partial")
    check("FAN-06: 4 pages", len(result.pages) == 4)
    # Page 0: success, Page 1: error, Page 2-3: success
    check("FAN-06: Page 0 success", result.pages[0].status == "success")
    check("FAN-06: Page 1 error", result.pages[1].status == "error")
    check("FAN-06: Page 1 has error message", "Simulated failure" in (result.pages[1].error or ""))

def test_stream_manager_sequential_all_failures():
    """FAN-07: All pages failing → status="failed"."""
    from app.services.ai.fanout import StreamManager
    manager = StreamManager(max_concurrency=3)

    async def always_fail(**kwargs):
        raise RuntimeError("Always fails")

    pages = [{"title": "P1"}, {"title": "P2"}]
    templates = [{"template_type": "content-text"}, {"template_type": "content-text"}]

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-job-003",
        pages=pages, templates=templates,
        rag_context=[], course_context={},
        generate_func=always_fail,
    ))
    check("FAN-07: Status failed", result.status == "failed")
    check("FAN-07: 2 pages attempted", len(result.pages) == 2)
    check("FAN-07: All error", all(p.status == "error" for p in result.pages))

def test_stream_manager_concurrency_respected():
    """FAN-08: Max concurrency limits concurrent workers."""
    from app.services.ai.fanout import StreamManager

    concurrent_calls = []
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def tracking_generate(**kwargs):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return await _mock_generate(**kwargs)

    manager = StreamManager(max_concurrency=2)  # Only 2 concurrent
    pages = [{"title": f"P{i}"} for i in range(8)]
    templates = [{"template_type": "content-text"} for _ in range(8)]

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-job-conc",
        pages=pages, templates=templates,
        rag_context=[], course_context={},
        generate_func=tracking_generate,
    ))
    check("FAN-08: Max concurrency <= 2", max_active <= 2, f"max_active={max_active}")
    check("FAN-08: All 8 pages done", len(result.pages) == 8)

def test_stream_manager_result_order_maintained():
    """FAN-09: Results maintain original page order regardless of completion order."""
    from app.services.ai.fanout import StreamManager

    async def variable_speed_generate(page_index=0, **kwargs):
        # Higher index pages finish faster (reverse order)
        delay = max(0.001, (8 - page_index) * 0.005)
        await asyncio.sleep(delay)
        return await _mock_generate(page_index=page_index, **kwargs)

    manager = StreamManager(max_concurrency=4)
    pages = [{"title": f"P{i}"} for i in range(8)]
    templates = [{"template_type": "content-text"} for _ in range(8)]

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-job-order",
        pages=pages, templates=templates,
        rag_context=[], course_context={},
        generate_func=variable_speed_generate,
    ))
    # Results MUST be in original order (page_index 0, 1, 2, ...)
    for i, p in enumerate(result.pages):
        check(f"FAN-09: Result[{i}] has page_index={i}", p.page_index == i,
              f"Got page_index={p.page_index} at position {i}")

def test_stream_manager_empty_pages():
    """FAN-10: Empty page list → success with 0 pages."""
    from app.services.ai.fanout import StreamManager
    manager = StreamManager()

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-job-empty",
        pages=[], templates=[],
        rag_context=[], course_context={},
        generate_func=_mock_generate,
    ))
    check("FAN-10: Has pages key", "pages" in result.__dict__ or len(result.pages) == 0)
    check("FAN-10: 0 pages", len(result.pages) == 0)
    check("FAN-10: job_id set", len(result.job_id) > 0)

def test_stream_manager_single_page():
    """FAN-11: Single page generation works."""
    from app.services.ai.fanout import StreamManager
    manager = StreamManager()

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-job-single",
        pages=[{"title": "Only Page"}],
        templates=[{"template_type": "tabs"}],
        rag_context=[], course_context={"title": "Course"},
        generate_func=_mock_generate,
    ))
    check("FAN-11: 1 page", len(result.pages) == 1)
    check("FAN-11: Success", result.pages[0].status == "success")
    check("FAN-11: Template preserved", result.pages[0].data["template_type"] == "tabs")

def test_stream_manager_fallback_detection():
    """FAN-12: Falls back to sequential when Redis unavailable."""
    from app.services.ai.fanout import StreamManager

    # Create manager that can't reach Redis (fresh manager, no Redis running)
    manager = StreamManager(redis_url="redis://nonexistent-host:9999")
    async def simple_gen(**kwargs):
        return {"title": "ok", "template_type": "content-text", "order": kwargs.get("page_index", 0), "components": []}

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-fallback",
        pages=[{"title": "P1"}],
        templates=[{"template_type": "content-text"}],
        rag_context=[], course_context={},
        generate_func=simple_gen,
    ))
    check("FAN-12: Backend is sequential (not redis)", result.backend == "sequential")

def test_stream_manager_progress_without_redis():
    """FAN-13: get_stream_progress returns empty when Redis unavailable."""
    from app.services.ai.fanout import StreamManager
    manager = StreamManager()

    progress = asyncio.run(manager.get_stream_progress("any-job-id"))
    check("FAN-13: Returns dict", isinstance(progress, dict))
    check("FAN-13: total=0 or 'unknown'", progress.get("total") in (0, "unknown"))

def test_stream_manager_duration_tracking():
    """FAN-14: total_duration_ms tracks wall-clock time."""
    from app.services.ai.fanout import StreamManager
    manager = StreamManager()

    async def slow_gen(**kwargs):
        await asyncio.sleep(0.02)
        return {"title": "ok", "template_type": "content-text", "order": kwargs.get("page_index", 0), "components": []}

    pages = [{"title": f"P{i}"} for i in range(3)]
    templates = [{"template_type": "content-text"} for _ in range(3)]

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-duration", pages=pages, templates=templates,
        rag_context=[], course_context={}, generate_func=slow_gen,
    ))
    check("FAN-14: Duration >= 20ms (3 pages × 20ms sleep, semaphored)",
          result.total_duration_ms >= 20.0)
    check("FAN-14: Duration < 5000ms (shouldn't hang)",
          result.total_duration_ms < 5000.0)

def test_stream_manager_default_concurrency():
    """FAN-15: Default max_concurrency from env or 3."""
    from app.services.ai.fanout import StreamManager
    m = StreamManager()
    check("FAN-15: Default concurrency >= 1", m.max_concurrency >= 1)

def test_stream_manager_generate_func_gets_correct_args():
    """FAN-16: generate_func receives all expected arguments."""
    from app.services.ai.fanout import StreamManager

    received_args = []

    async def args_checker(**kwargs):
        received_args.append(kwargs)
        return await _mock_generate(**kwargs)

    manager = StreamManager(max_concurrency=1)
    result = asyncio.run(manager.fan_out_pages(
        job_id="test-args",
        pages=[{"title": "My Page", "source_content": "test content"}],
        templates=[{"template_type": "accordion", "confidence": 0.9}],
        rag_context=[{"title": "Similar Course"}],
        course_context={"title": "Course X", "audience": "experts"},
        generate_func=args_checker,
    ))
    # Only need to check first call received all args
    kw = received_args[0]
    check("FAN-16: Has page_plan", "page_plan" in kw)
    check("FAN-16: Has template_assignment", "template_assignment" in kw)
    check("FAN-16: Has rag_context", "rag_context" in kw)
    check("FAN-16: Has course_context", "course_context" in kw)
    check("FAN-16: Has page_index", "page_index" in kw)
    check("FAN-16: Has total_pages", "total_pages" in kw)
    check("FAN-16: page_index=0", kw["page_index"] == 0)
    check("FAN-16: total_pages=1", kw["total_pages"] == 1)


# ═══════════════════════════════════════════════════════════════════════
# Integration with agents
# ═══════════════════════════════════════════════════════════════════════

def test_fanout_integration_with_content_generator():
    """FAN-17: Fan-out works with real ContentGeneratorAgent."""
    from app.services.ai.fanout import StreamManager
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent

    agent = ContentGeneratorAgent(llm_client=None)  # Mock mode (no LLM)

    async def agent_generate(page_plan, template_assignment, rag_context,
                             course_context, page_index, total_pages):
        return await agent.generate_page(
            page_plan=page_plan,
            template_assignment=template_assignment,
            rag_context=rag_context,
            course_context=course_context,
            page_index=page_index,
            total_pages=total_pages,
        )

    manager = StreamManager(max_concurrency=2)
    pages = [
        {"title": "Intro", "source_content": "Welcome overview", "learning_objective": "Understand basics"},
        {"title": "Security Quiz", "source_content": "Quiz on security types", "learning_objective": "Evaluate knowledge"},
    ]
    templates = [
        {"template_type": "content-text"},
        {"template_type": "final-assessment"},
    ]

    result = asyncio.run(manager.fan_out_pages(
        job_id="test-agent-integration",
        pages=pages, templates=templates,
        rag_context=[], course_context={"title": "Security 101"},
        generate_func=agent_generate,
    ))
    check("FAN-17: 2 pages", len(result.pages) == 2)
    check("FAN-17: Success", result.status == "success")
    # Verify template types preserved
    check("FAN-17: Page 0 content-text",
          result.pages[0].data["template_type"] == "content-text")
    check("FAN-17: Page 1 final-assessment",
          result.pages[1].data["template_type"] == "final-assessment")


# ═══════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Fan-Out Tests — Redis Streams Manager + Sequential Fallback")
    print("=" * 60)

    print("\n--- Dataclasses ---")
    test_page_message_dataclass()
    test_page_result_dataclass()
    test_fanout_result_dataclass()

    print("\n--- StreamManager: Sequential Fallback ---")
    test_stream_manager_import()
    test_stream_manager_sequential_basic()
    test_stream_manager_sequential_with_failures()
    test_stream_manager_sequential_all_failures()
    test_stream_manager_concurrency_respected()
    test_stream_manager_result_order_maintained()
    test_stream_manager_empty_pages()
    test_stream_manager_single_page()
    test_stream_manager_fallback_detection()
    test_stream_manager_progress_without_redis()
    test_stream_manager_duration_tracking()
    test_stream_manager_default_concurrency()
    test_stream_manager_generate_func_gets_correct_args()

    print("\n--- Integration with ContentGeneratorAgent ---")
    test_fanout_integration_with_content_generator()

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    if failures:
        print("\nFAILURES:")
        for name, detail in failures:
            print(f"  {name}: {detail}")
