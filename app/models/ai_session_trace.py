"""Session Trace Model — Full I/O audit for LLM, RAG, DB operations per session.

Each row is one span in a session's call tree. Spans can be nested via
parent_span_id. The trace for a session reconstructs the full request
lifecycle: LLM prompts/responses, tool executions, RAG retrievals,
and DB operations — all with timestamps, latencies, and payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


class AISessionTraceSpan(Base):
    """A single operation span within a session trace.

    Trace types:
        llm_request   — Full prompt + tools sent to LLM
        llm_response  — Full response from LLM (text or tool_use)
        tool_call     — Tool execution request
        tool_result   — Tool execution result
        rag_retrieval — Similar course search (tier, query, results)
        db_operation  — Database query with params
        context_prune — Token pruning decision
        orchestrator  — Loop iteration marker
    """

    __tablename__ = "ai_session_trace_spans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    span_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid,
    )
    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    trace_id: Mapped[str] = mapped_column(
        String(64), index=True, default=_uuid,
    )
    parent_span_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
    )

    # ── Classification ─────────────────────────────────────────
    trace_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        # llm_request | llm_response | tool_call | tool_result
        # | rag_retrieval | db_operation | context_prune | orchestrator
    )
    operation: Mapped[str] = mapped_column(
        String(128), nullable=False,
        # e.g. "chat", "list_pages", "query_similar_courses",
        # "generate_embedding", "search_vector", "upsert_course"
    )

    # ── Payloads (full I/O) ────────────────────────────────────
    input_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── LLM-specific ───────────────────────────────────────────
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # {"input": N, "output": N, "cache_read": N, "cache_write": N}

    # ── Timing ─────────────────────────────────────────────────
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )

    # ── Status ─────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(16), default="success")
    # "success" | "error"
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Metadata ───────────────────────────────────────────────
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSON, nullable=True,
    )
    # Arbitrary tags: provider, tier, retry_count, etc.

    __table_args__ = (
        Index("ix_trace_session_created", "session_id", "created_at"),
        Index("ix_trace_type_session", "trace_type", "session_id"),
    )

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "trace_type": self.trace_type,
            "operation": self.operation,
            "input_payload": self.input_payload,
            "output_payload": self.output_payload,
            "model": self.model,
            "token_usage": self.token_usage,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error_message": self.error_message,
            "metadata": self.metadata_,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
