"""Session Tracer — Full I/O capture for LLM, RAG, DB, Tool operations.

Provides span lifecycle management with in-memory buffering and optional
DB persistence. Query by session_id returns the complete call tree.

Usage:
    tracer = SessionTracer(db)          # DB-backed persistence
    tracer = SessionTracer()            # In-memory only (testing)

    span = await tracer.start_span(
        session_id="...",
        trace_type="llm_request",
        operation="chat",
        input_payload={...},
    )
    # ... do work ...
    await tracer.end_span(
        span_id=span["span_id"],
        output_payload={...},
        token_usage={...},
        latency_ms=1234.5,
    )

    # Query full trace:
    trace = await tracer.get_session_trace(session_id)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── In-memory buffer (shared across instances when DB unavailable) ──
_memory_store: Dict[str, List[Dict[str, Any]]] = {}  # session_id → [spans]


class SessionTracer:
    """Captures full I/O for every operation in a session lifecycle.

    Two modes:
        - DB mode (db=AsyncSession): persists spans to ai_session_trace_spans table
        - Memory mode (db=None): stores in _memory_store dict (for tests)

    All public methods accept `session_id` explicitly — no implicit state.
    """

    def __init__(self, db=None):
        self.db = db
        self._use_db = db is not None
        self._store = _memory_store

    # ── Public API ──────────────────────────────────────────────────

    async def start_span(
        self,
        session_id: str,
        trace_type: str,
        operation: str,
        parent_span_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        input_payload: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Begin a trace span. Returns the span dict for use in end_span().

        Args:
            session_id: The AI session being traced.
            trace_type: One of llm_request, llm_response, tool_call,
                        tool_result, rag_retrieval, db_operation,
                        context_prune, orchestrator.
            operation: Human-readable operation name
                       (e.g. "chat", "list_pages", "query_similar_courses").
            parent_span_id: For nesting spans in a call tree.
            trace_id: Shared across all spans in one API request.
                      Auto-generated if omitted.
            input_payload: Full input/request data (dict, serialisable).
            model: LLM model name (for llm_* spans).
            metadata: Arbitrary tags (provider, tier, retry_count, etc.).

        Returns:
            Span dict with span_id, trace_id, session_id, started_at.
            Pass this to end_span().
        """
        from app.models.ai_session_trace import _uuid as _gen_uuid

        span_id = _gen_uuid()
        effective_trace_id = trace_id or _gen_uuid()
        started_at = time.perf_counter()

        span_data = {
            "span_id": span_id,
            "session_id": session_id,
            "trace_id": effective_trace_id,
            "parent_span_id": parent_span_id,
            "trace_type": trace_type,
            "operation": operation,
            "input_payload": input_payload,
            "model": model,
            "metadata": metadata,
            "status": "success",
            "created_at": datetime.utcnow(),
            "_started_at": started_at,  # Internal — not persisted
        }

        # Store in memory immediately so the span is visible even
        # if the operation crashes. Flushed to DB in end_span().
        self._store.setdefault(session_id, []).append(span_data)

        return span_data

    async def end_span(
        self,
        span: Dict[str, Any],
        output_payload: Optional[Dict[str, Any]] = None,
        token_usage: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[float] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Complete a trace span with output and timing.

        Args:
            span: The span dict returned by start_span().
            output_payload: Full output/response data.
            token_usage: For LLM spans: {"input": N, "output": N}.
            latency_ms: Wall-clock duration. Auto-computed from start_span
                        if the span has _started_at.
            status: "success" or "error".
            error_message: Error description if status="error".

        Returns:
            The completed span dict (persisted).
        """
        # Compute latency if not explicitly provided
        if latency_ms is None and "_started_at" in span:
            latency_ms = (time.perf_counter() - span.pop("_started_at")) * 1000
        else:
            span.pop("_started_at", None)

        # Update mutable fields
        span["output_payload"] = output_payload
        span["token_usage"] = token_usage
        span["latency_ms"] = round(latency_ms, 3) if latency_ms else None
        span["status"] = status
        span["error_message"] = error_message
        if metadata:
            span["metadata"] = {**(span.get("metadata") or {}), **metadata}

        await self._persist_span(span)
        return span

    async def get_session_trace(
        self,
        session_id: str,
        limit: int = 200,
        trace_types: Optional[List[str]] = None,
        min_latency_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return the full trace tree for a session.

        Args:
            session_id: The AI session to query.
            limit: Max spans to return.
            trace_types: Filter by span types (e.g. ["llm_request", "tool_call"]).
            min_latency_ms: Only include spans slower than this threshold.

        Returns:
            {
                "session_id": str,
                "total_spans": int,
                "spans": [...],  # time-ordered, oldest first
                "by_type": {...},  # count per trace_type
                "by_operation": {...},  # count per operation
                "aggregates": {
                    "total_llm_calls": int,
                    "total_tool_calls": int,
                    "total_rag_retrievals": int,
                    "total_db_operations": int,
                    "total_latency_ms": float,
                    "total_tokens": {"input": N, "output": N},
                    "models_used": [...],
                    "errors": int,
                },
            }
        """
        all_spans = await self._get_spans(session_id)

        # Apply filters
        if trace_types:
            all_spans = [s for s in all_spans if s.get("trace_type") in trace_types]
        if min_latency_ms is not None:
            all_spans = [
                s for s in all_spans
                if (s.get("latency_ms") or 0) >= min_latency_ms
            ]

        # Sort by created_at asc
        all_spans.sort(key=lambda s: str(s.get("created_at", "")))

        # Enforce limit
        results = all_spans[:limit]

        # ── Aggregates ──────────────────────────────────────────
        by_type: Dict[str, int] = {}
        by_operation: Dict[str, int] = {}
        total_llm = 0
        total_tools = 0
        total_rag = 0
        total_db = 0
        total_latency = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        models_used: set = set()
        errors = 0

        for s in all_spans:
            tt = s.get("trace_type", "unknown")
            op = s.get("operation", "unknown")
            by_type[tt] = by_type.get(tt, 0) + 1
            by_operation[op] = by_operation.get(op, 0) + 1

            if tt.startswith("llm"):
                total_llm += 1
            elif tt.startswith("tool"):
                total_tools += 1
            elif tt == "rag_retrieval":
                total_rag += 1
            elif tt == "db_operation":
                total_db += 1

            if s.get("latency_ms"):
                total_latency += s["latency_ms"]

            tu = s.get("token_usage") or {}
            total_input_tokens += tu.get("input", 0)
            total_output_tokens += tu.get("output", 0)

            if s.get("model"):
                models_used.add(s["model"])

            if s.get("status") == "error":
                errors += 1

        return {
            "session_id": session_id,
            "total_spans": len(all_spans),
            "shown_spans": len(results),
            "truncated": len(all_spans) > limit,
            "spans": [self._span_to_dict(s) for s in results],
            "by_type": by_type,
            "by_operation": by_operation,
            "aggregates": {
                "total_llm_calls": total_llm,
                "total_tool_calls": total_tools,
                "total_rag_retrievals": total_rag,
                "total_db_operations": total_db,
                "total_latency_ms": round(total_latency, 3),
                "total_tokens": {
                    "input": total_input_tokens,
                    "output": total_output_tokens,
                },
                "models_used": sorted(models_used),
                "errors": errors,
            },
        }

    async def clear_session(self, session_id: str) -> int:
        """Delete all trace spans for a session. Returns count deleted."""
        # Clear memory
        count = len(self._store.pop(session_id, []))

        # Clear DB if available
        if self._use_db:
            try:
                from sqlalchemy import delete
                from app.models.ai_session_trace import AISessionTraceSpan

                result = await self.db.execute(
                    delete(AISessionTraceSpan).where(
                        AISessionTraceSpan.session_id == session_id
                    )
                )
                await self.db.commit()
                count += result.rowcount
            except Exception:
                try:
                    await self.db.rollback()
                except Exception:
                    pass
        return count

    # ── Internal helpers ────────────────────────────────────────────

    async def _persist_span(self, span: Dict[str, Any]) -> None:
        """Write span to DB (once, from end_span). Updates in-memory copy.

        In memory mode: replaces any stub added by start_span.
        In DB mode: inserts the completed span.
        """
        # Always update in-memory (deduplicate by span_id)
        session_spans = self._store.setdefault(span["session_id"], [])
        for i, existing in enumerate(session_spans):
            if existing.get("span_id") == span["span_id"]:
                session_spans[i] = span
                break
        else:
            session_spans.append(span)

        if self._use_db:
            try:
                from app.models.ai_session_trace import AISessionTraceSpan

                record = AISessionTraceSpan(
                    span_id=span["span_id"],
                    session_id=span["session_id"],
                    trace_id=span.get("trace_id", ""),
                    parent_span_id=span.get("parent_span_id"),
                    trace_type=span["trace_type"],
                    operation=span["operation"],
                    input_payload=span.get("input_payload"),
                    output_payload=span.get("output_payload"),
                    model=span.get("model"),
                    token_usage=span.get("token_usage"),
                    latency_ms=span.get("latency_ms"),
                    status=span.get("status", "success"),
                    error_message=span.get("error_message"),
                    metadata_=span.get("metadata"),
                    created_at=span.get("created_at", datetime.utcnow()),
                )
                self.db.add(record)
                # Use a nested commit so trace failures don't break
                # the parent transaction.
                await self.db.commit()
            except Exception:
                # Non-fatal: trace persistence failures must never
                # break the actual API call. Data stays in memory.
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                # Disable future DB attempts for this tracer instance
                self._use_db = False

    async def _get_spans(self, session_id: str) -> List[Dict[str, Any]]:
        """Retrieve all spans for a session. Memory-first, DB as fallback."""
        # Memory always works
        mem_spans = list(self._store.get(session_id, []))
        seen = {s.get("span_id") for s in mem_spans}

        # Merge with DB if available
        if self._use_db:
            try:
                from sqlalchemy import select
                from app.models.ai_session_trace import AISessionTraceSpan

                result = await self.db.execute(
                    select(AISessionTraceSpan)
                    .where(AISessionTraceSpan.session_id == session_id)
                    .order_by(AISessionTraceSpan.created_at.asc())
                )
                for s in result.scalars().all():
                    d = s.to_dict()
                    sid = d.get("span_id")
                    if sid and sid not in seen:
                        seen.add(sid)
                        mem_spans.append(d)
            except Exception:
                pass  # DB unavailable — memory data is sufficient
        return mem_spans

    @staticmethod
    def _span_to_dict(span: Dict[str, Any]) -> Dict[str, Any]:
        """Strip internal keys before returning to API."""
        return {
            k: v for k, v in span.items()
            if not k.startswith("_")
        }


# ── Singleton convenience ──────────────────────────────────────────

_tracer_instance: Optional[SessionTracer] = None


def get_tracer(db=None) -> SessionTracer:
    """Return a SessionTracer, creating one if needed.

    Without a DB session, uses in-memory store only.
    With a DB session, persists to ai_session_trace_spans table.
    """
    global _tracer_instance
    if db is not None:
        return SessionTracer(db)
    if _tracer_instance is None:
        _tracer_instance = SessionTracer()
    return _tracer_instance
