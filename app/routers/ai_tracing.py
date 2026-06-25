"""AI Session Tracing Router — Full I/O audit per session.

Endpoints:
    GET  /api/v1/ai/sessions/{session_id}/trace     — Full trace tree
    GET  /api/v1/ai/sessions/{session_id}/trace/summary — Aggregates only
    DELETE /api/v1/ai/sessions/{session_id}/trace   — Clear trace data
"""

from __future__ import annotations

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session as get_db_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.services.ai.session_tracer import SessionTracer
from app.services.ai.error_envelope import ai_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI - Session Tracing"])


# ── Public Endpoints ───────────────────────────────────────────────

@router.get("/sessions/{session_id}/trace")
async def get_session_trace(
    session_id: str,
    trace_types: Optional[str] = Query(
        None,
        description="Comma-separated filter: llm_request,llm_response,tool_call,"
                    "tool_result,rag_retrieval,db_operation,context_prune,orchestrator",
    ),
    min_latency_ms: Optional[float] = Query(
        None,
        description="Only include spans taking at least this many ms",
    ),
    limit: int = Query(200, ge=1, le=1000, description="Max spans to return"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the complete session trace tree with full LLM/RAG/DB I/O.

    Each span captures:
        - LLM calls: exact prompt (system + messages + tools), response
          content, tool_use decisions, token counts, latency, model used
        - Tool executions: input params, output results, status
        - RAG retrievals: query embedding, search tier used, result set,
          per-tier timing
        - DB operations: query type, table, key parameters
        - Context pruning: messages removed, token delta, strategy used

    Aggregates include totals for tokens, latency, calls per type, and
    error counts.

    Filter by trace_types to focus on specific layers, or by
    min_latency_ms to find slow operations.
    """
    type_list = None
    if trace_types:
        type_list = [t.strip() for t in trace_types.split(",") if t.strip()]

    tracer = SessionTracer(db)
    trace = await tracer.get_session_trace(
        session_id=session_id,
        limit=limit,
        trace_types=type_list,
        min_latency_ms=min_latency_ms,
    )

    return {"status": "ok", **trace}


@router.get("/sessions/{session_id}/trace/summary")
async def get_session_trace_summary(
    session_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Return aggregated trace summary only (no span payloads).

    Faster than full trace — returns counts, totals, models used,
    latency breakdown, and error summary without I/O payloads.
    """
    tracer = SessionTracer(db)
    trace = await tracer.get_session_trace(session_id=session_id, limit=0)

    return {
        "status": "ok",
        "session_id": trace["session_id"],
        "total_spans": trace["total_spans"],
        "by_type": trace["by_type"],
        "by_operation": trace["by_operation"],
        "aggregates": trace["aggregates"],
    }


@router.delete("/sessions/{session_id}/trace")
async def clear_session_trace(
    session_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Delete all trace data for a session.

    Useful for clearing test data or resetting trace collection.
    """
    tracer = SessionTracer(db)
    deleted = await tracer.clear_session(session_id)
    return {
        "status": "ok",
        "session_id": session_id,
        "spans_deleted": deleted,
    }
