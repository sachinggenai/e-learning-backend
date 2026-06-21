"""Durable workflow engine ORM models — US-BKND-AI-034.

Tables:
    workflow_type_definitions  — Registry of workflow types (state machines)
    workflow_jobs              — Primary job table with heartbeat/locking
    workflow_job_events        — Immutable event log (append-only)

Follows the same dual-key pattern (int PK + UUID string) and conventions
as app/models/ai_models.py.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime,
    ForeignKey, Index, BigInteger,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _new_uuid() -> _uuid.UUID:
    """Generate a new UUID v4. Used as default for job_id."""
    return _uuid.uuid4()


# ═══════════════════════════════════════════════════════════════════
# Workflow Type Definitions
# ═══════════════════════════════════════════════════════════════════

class WorkflowTypeDefinition(Base):
    __tablename__ = "workflow_type_definitions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_type: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state_machine: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_wf_type_def_active", "workflow_type",
              postgresql_where=(is_active == True)),  # noqa: E712
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflowType": self.workflow_type,
            "displayName": self.display_name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "stateMachine": self.state_machine,
            "outputSchema": self.output_schema,
            "maxDurationSeconds": self.max_duration_seconds,
            "isActive": self.is_active,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


# ═══════════════════════════════════════════════════════════════════
# Workflow Jobs
# ═══════════════════════════════════════════════════════════════════

class WorkflowJob(Base):
    __tablename__ = "workflow_jobs"

    # ── Keys ───────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, default=_new_uuid,
        server_default=__import__("sqlalchemy").text("gen_random_uuid()"),
    )
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # ── State machine tracking ─────────────────────────────
    status: Mapped[str] = mapped_column(String(32), default="pending")
    current_state: Mapped[str] = mapped_column(String(128), default="validate_input")
    previous_state: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # ── Input / Output ─────────────────────────────────────
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    checkpoint_data: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ── Progress ───────────────────────────────────────────
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Retry tracking ─────────────────────────────────────
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    current_retry_state: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # ── Timing ─────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # ── Heartbeat & Locking ────────────────────────────────
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ── Webhook ────────────────────────────────────────────
    webhook_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    webhook_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Priority queue ─────────────────────────────────────
    priority: Mapped[int] = mapped_column(Integer, default=0)

    # ── User context ───────────────────────────────────────
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[Optional[_uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ai_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Expiry ─────────────────────────────────────────────
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.utcnow() + timedelta(hours=24),
    )

    # ── Table-level constraints ────────────────────────────
    __table_args__ = (
        Index("idx_wf_jobs_status", "status",
              postgresql_where=(status.in_(["pending", "running"]))),
        Index("idx_wf_jobs_type_status", "workflow_type", "status"),
        Index("idx_wf_jobs_locked_by", "locked_by",
              postgresql_where=(locked_by.isnot(None))),
        Index("idx_wf_jobs_heartbeat", "heartbeat_at",
              postgresql_where=(status == "running")),
        Index("idx_wf_jobs_expires", "expires_at",
              postgresql_where=(status.notin_(["complete", "cancelled"]))),
    )

    def to_dict(self) -> dict:
        return {
            "jobId": str(self.job_id),
            "workflowType": self.workflow_type,
            "status": self.status,
            "currentState": self.current_state,
            "previousState": self.previous_state,
            "input": self.input,
            "result": self.result,
            "error": self.error,
            "checkpointData": self.checkpoint_data,
            "progress": self.progress,
            "retryCount": self.retry_count,
            "maxRetries": self.max_retries,
            "currentRetryState": self.current_retry_state,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "heartbeatAt": self.heartbeat_at.isoformat() if self.heartbeat_at else None,
            "lockedBy": self.locked_by,
            "webhookUrl": self.webhook_url,
            "webhookSentAt": self.webhook_sent_at.isoformat() if self.webhook_sent_at else None,
            "priority": self.priority,
            "createdByUserId": self.created_by_user_id,
            "sessionId": str(self.session_id) if self.session_id else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
        }

    @property
    def is_terminal(self) -> bool:
        """True if the job is in a terminal state."""
        return self.status in ("complete", "failed", "cancelled") if self.status else False

    @property
    def is_expired(self) -> bool:
        """True if the job has passed its expiry time."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


# ═══════════════════════════════════════════════════════════════════
# Workflow Job Events
# ═══════════════════════════════════════════════════════════════════

class WorkflowJobEvent(Base):
    __tablename__ = "workflow_job_events"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    job_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_wf_events_job", "job_id", "timestamp"),
        Index("idx_wf_events_type", "event_type"),
    )

    def to_dict(self) -> dict:
        return {
            "eventId": self.id,
            "jobId": str(self.job_id),
            "state": self.state,
            "eventType": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
