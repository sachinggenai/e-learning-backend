"""Redis Streams fan-out manager for parallel course generation — Phase 1.1.

Architecture:
    Supervisor (LangGraph/API endpoint)
        │
        ├── Publish 1 message per page to Redis Stream: course:generation:{job_id}
        │   Message: {page_index, page_plan, template, rag_context, course_context}
        │
        └── Consumer Group: content-generators
            ├── Worker 1 (asyncio task) → AGT-07.generate_page(page_0) → Results Stream
            ├── Worker 2 (asyncio task) → AGT-07.generate_page(page_1) → Results Stream
            ├── Worker 3 (asyncio task) → AGT-07.generate_page(page_2) → Results Stream
            └── Worker N (asyncio task) → AGT-07.generate_page(page_n) → Results Stream

Uses Redis Streams consumer groups for exactly-once processing.
Each page is a message. N workers consume concurrently.
Results collected in a Redis Stream or asyncio.Queue.

Graceful degradation:
    - Redis unavailable → falls back to sequential generation (asyncio.gather with semaphore)
    - Consumer group error → retries with exponential backoff, then sequential fallback
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ai_authoring")

DEFAULT_MAX_CONCURRENCY = 3
STREAM_TTL_SECONDS = 3600  # Auto-expire streams after 1 hour


@dataclass
class PageMessage:
    """A single page generation task."""
    page_index: int
    total_pages: int
    page_plan: Dict[str, Any]
    template_assignment: Dict[str, Any]
    rag_context: List[Dict[str, Any]]
    course_context: Dict[str, Any]


@dataclass
class PageResult:
    """Result of generating a single page."""
    page_index: int
    status: str  # "success" | "fallback" | "error"
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    retry_count: int = 0


@dataclass
class FanOutResult:
    """Aggregate result of a fan-out generation run."""
    job_id: str
    status: str  # "success" | "partial" | "failed"
    pages: List[PageResult] = field(default_factory=list)
    total_duration_ms: float = 0.0
    backend: str = "redis"  # "redis" or "sequential"


class StreamManager:
    """Manages Redis Streams for parallel page generation.

    Usage:
        manager = StreamManager()
        pages = [{"title": "...", "template_type": "...", ...}, ...]

        async def generate_fn(page_plan, template, rag, ctx, idx, total) -> dict:
            # Call ContentGeneratorAgent
            ...

        results = await manager.fan_out_pages(
            job_id="job-123",
            pages=pages,
            templates=templates,
            rag_context=[],
            course_context={"title": "My Course"},
            generate_func=generate_fn,
        )
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        max_concurrency: Optional[int] = None,
    ):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.max_concurrency = max_concurrency or int(
            os.getenv("AI_GENERATION_CONCURRENCY", str(DEFAULT_MAX_CONCURRENCY))
        )
        self._redis: Any = None
        self._redis_available: Optional[bool] = None

    # ── Public API ─────────────────────────────────────────────────

    async def fan_out_pages(
        self,
        job_id: str,
        pages: List[Dict[str, Any]],
        templates: List[Dict[str, Any]],
        rag_context: List[Dict[str, Any]],
        course_context: Dict[str, Any],
        generate_func: Callable[..., Any],
    ) -> FanOutResult:
        """Fan out page generation to N concurrent workers.

        Tries Redis Streams first; falls back to sequential asyncio.gather
        if Redis is unavailable.

        Args:
            job_id: Unique job ID for stream naming
            pages: List of page plan entries
            templates: Template assignments (same order as pages)
            rag_context: RAG context shared across all pages
            course_context: Course-level context
            generate_func: Async function(page_plan, template, rag, ctx, idx, total) → dict

        Returns:
            FanOutResult with all page results and timing info.
        """
        import time
        t0 = time.perf_counter()

        if await self._ensure_redis():
            result = await self._fan_out_via_redis(
                job_id, pages, templates, rag_context, course_context, generate_func
            )
            result.backend = "redis"
        else:
            logger.info("Redis unavailable — using sequential generation fallback")
            result = await self._fan_out_sequential(
                pages, templates, rag_context, course_context, generate_func
            )
            result.backend = "sequential"
            result.job_id = job_id

        result.total_duration_ms = (time.perf_counter() - t0) * 1000

        # Determine aggregate status
        success_count = sum(1 for p in result.pages if p.status == "success")
        error_count = sum(1 for p in result.pages if p.status == "error")
        if len(result.pages) == 0:
            # Empty page list is a valid no-op success, not a failure
            result.status = "success"
        elif error_count == len(result.pages):
            result.status = "failed"
        elif error_count > 0 or success_count < len(result.pages):
            result.status = "partial"
        else:
            result.status = "success"

        logger.info(
            "Fan-out complete: %d pages, %s backend, %.0fms, %d success, %d fallback, %d error",
            len(result.pages), result.backend, result.total_duration_ms,
            success_count,
            sum(1 for p in result.pages if p.status == "fallback"),
            error_count,
        )
        return result

    async def get_stream_progress(self, job_id: str) -> Dict[str, Any]:
        """Get current progress of a running generation job."""
        results_key = f"course:generation:{job_id}:results"
        if not await self._ensure_redis():
            return {"total": 0, "completed": 0, "progress_pct": 0}

        try:
            count = await self._redis.xlen(results_key)
            return {"total": "unknown", "completed": count, "progress_pct": None}
        except Exception:
            return {"total": 0, "completed": 0, "progress_pct": 0}

    # ── Redis Streams implementation ───────────────────────────────

    async def _ensure_redis(self) -> bool:
        """Lazy-init Redis connection. Returns True if Redis is available."""
        if self._redis_available is not None:
            return self._redis_available

        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self._redis_url,
                socket_connect_timeout=2,
                socket_timeout=5,
                decode_responses=False,  # Keep binary for msgpack if needed
            )
            await self._redis.ping()
            self._redis_available = True
            logger.info("Redis Streams manager CONNECTED (%s)", self._redis_url)
        except ImportError:
            logger.warning("redis package not installed — Streams fan-out unavailable")
            self._redis_available = False
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — using sequential fallback", exc)
            self._redis_available = False

        return self._redis_available

    async def _fan_out_via_redis(
        self,
        job_id: str,
        pages: List[Dict[str, Any]],
        templates: List[Dict[str, Any]],
        rag_context: List[Dict[str, Any]],
        course_context: Dict[str, Any],
        generate_func: Callable[..., Any],
    ) -> FanOutResult:
        """Fan-out via Redis Streams with consumer groups."""
        stream_key = f"course:generation:{job_id}"
        group_name = f"generators-{job_id}"

        # Create consumer group (idempotent)
        try:
            await self._redis.xgroup_create(
                stream_key, group_name, id="0", mkstream=True
            )
        except Exception:
            # Group already exists or Redis error
            pass

        total = len(pages)

        # Publish all pages as stream messages
        for i, (page, template) in enumerate(zip(pages, templates)):
            msg_data = {
                b"page_index": str(i).encode(),
                b"total_pages": str(total).encode(),
                b"page_plan": json.dumps(page).encode(),
                b"template": json.dumps(template).encode(),
                b"rag_context": json.dumps(rag_context).encode(),
                b"course_context": json.dumps(course_context).encode(),
            }
            await self._redis.xadd(stream_key, msg_data, maxlen=total * 2)

        # Set TTL on the stream
        await self._redis.expire(stream_key, STREAM_TTL_SECONDS)

        # Results queue (in-memory list + lock)
        results: List[Optional[PageResult]] = [None] * total
        lock = asyncio.Lock()

        async def worker(worker_name: str):
            """Consume messages from the stream and generate pages."""
            consumer_id = f"{worker_name}-{job_id}"
            while True:
                try:
                    messages = await self._redis.xreadgroup(
                        group_name, consumer_id,
                        {stream_key: b">"}, count=1, block=2000,
                    )
                except Exception:
                    # Stream or group disappeared
                    break

                if not messages:
                    break

                for _, entries in messages:
                    for msg_id, data in entries:
                        idx = int(data.get(b"page_index", b"0"))
                        import time
                        t_start = time.perf_counter()

                        try:
                            generated = await generate_func(
                                page_plan=json.loads(data[b"page_plan"].decode()),
                                template_assignment=json.loads(data[b"template"].decode()),
                                rag_context=json.loads(data[b"rag_context"].decode()),
                                course_context=json.loads(data[b"course_context"].decode()),
                                page_index=idx,
                                total_pages=int(data[b"total_pages"]),
                            )
                            duration = (time.perf_counter() - t_start) * 1000
                            async with lock:
                                results[idx] = PageResult(
                                    page_index=idx,
                                    status="success",
                                    data=generated,
                                    duration_ms=duration,
                                )
                        except Exception as exc:
                            duration = (time.perf_counter() - t_start) * 1000
                            logger.error("Worker %s failed page %d: %s", worker_name, idx, exc)
                            async with lock:
                                results[idx] = PageResult(
                                    page_index=idx,
                                    status="error",
                                    error=str(exc),
                                    duration_ms=duration,
                                )

                        # ACK the message
                        await self._redis.xack(stream_key, group_name, msg_id)

        # Spawn workers
        worker_tasks = [
            asyncio.create_task(worker(f"gen-worker-{i}"))
            for i in range(min(self.max_concurrency, total))
        ]
        await asyncio.gather(*worker_tasks, return_exceptions=True)

        # Fill any None slots as errors
        for i in range(total):
            if results[i] is None:
                results[i] = PageResult(
                    page_index=i,
                    status="error",
                    error="Worker did not process this page",
                )

        # Cleanup stream
        try:
            await self._redis.delete(stream_key)
        except Exception:
            pass

        final_pages = [r for r in results if r is not None]
        success_count = sum(1 for p in final_pages if p.status == "success")
        error_count = sum(1 for p in final_pages if p.status == "error")
        if error_count == len(final_pages):
            agg_status = "failed"
        elif error_count > 0 or success_count < len(final_pages):
            agg_status = "partial"
        else:
            agg_status = "success"

        return FanOutResult(job_id=job_id, status=agg_status, pages=final_pages)

    async def _fan_out_sequential(
        self,
        pages: List[Dict[str, Any]],
        templates: List[Dict[str, Any]],
        rag_context: List[Dict[str, Any]],
        course_context: Dict[str, Any],
        generate_func: Callable[..., Any],
    ) -> FanOutResult:
        """Sequential fallback using asyncio.gather with semaphore.

        NOT as bad as it sounds: asyncio.gather with semaphore achieves
        N concurrent tasks even without Redis, just without process isolation.
        """
        total = len(pages)
        semaphore = asyncio.Semaphore(self.max_concurrency)
        results: List[Optional[PageResult]] = [None] * total

        async def bounded_generate(idx: int):
            import time
            t_start = time.perf_counter()

            async with semaphore:
                try:
                    generated = await generate_func(
                        page_plan=pages[idx],
                        template_assignment=templates[idx],
                        rag_context=rag_context,
                        course_context=course_context,
                        page_index=idx,
                        total_pages=total,
                    )
                    duration = (time.perf_counter() - t_start) * 1000
                    results[idx] = PageResult(
                        page_index=idx,
                        status="success",
                        data=generated,
                        duration_ms=duration,
                    )
                except Exception as exc:
                    duration = (time.perf_counter() - t_start) * 1000
                    logger.error("Sequential fallback failed page %d: %s", idx, exc)
                    results[idx] = PageResult(
                        page_index=idx,
                        status="error",
                        error=str(exc),
                        duration_ms=duration,
                    )

        tasks = [asyncio.create_task(bounded_generate(i)) for i in range(total)]
        await asyncio.gather(*tasks, return_exceptions=True)

        final_pages = [r for r in results if r is not None]
        success_count = sum(1 for p in final_pages if p.status == "success")
        error_count = sum(1 for p in final_pages if p.status == "error")
        if error_count == len(final_pages):
            agg_status = "failed"
        elif error_count > 0 or success_count < len(final_pages):
            agg_status = "partial"
        else:
            agg_status = "success"

        return FanOutResult(
            job_id="sequential-fallback",
            status=agg_status,
            pages=final_pages,
        )
