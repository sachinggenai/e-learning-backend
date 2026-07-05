"""AI Persistence ORM models.

Covers sessions, proposals, confirmation tokens, audit logs,
outbox events, chat turns, and idempotency keys for the
AI authoring subsystem.

Follows the same dual-key pattern (int PK + string UUID) and
conventions as the rest of the codebase (see app/models/social.py,
app/models/page_component.py).

Tables:
    ai_sessions            — AI authoring session scoped to user+course+org
    ai_proposals           — AI-generated mutation proposals with lifecycle
    ai_confirmation_tokens — One-time tokens for destructive operations
    ai_audit_logs          — Append-only audit trail for all AI actions
    ai_outbox_events       — Transactional outbox for downstream consumers
    ai_chat_turns          — Chat conversation turns with tool call traces
    ai_idempotency_keys    — Idempotency key storage with response caching

TODO(AUTH): organization_id columns exist but tenant isolation queries
are not yet enforced at the repository/engine level (US-BKND-AI-021).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSON, Text, Integer, Boolean, Float, ForeignKey,
)

from app.models.base import Base


def _uuid() -> str:
    """Generate a UUID v4 string for external-facing identifiers."""
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════
# AI Sessions
# ═══════════════════════════════════════════════════════════════════

class AISessionRecord(Base):
    """An AI authoring session scoped to one user, course, and organization.

    Sessions have a configurable TTL (default 24h). Expired or revoked
    sessions reject all tool calls and chat messages.
    """

    __tablename__ = "ai_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    scope: Mapped[str] = mapped_column(String(16), default="page")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    def is_expired(self) -> bool:
        """Check if the session has passed its expiry time."""
        return datetime.utcnow() > self.expires_at

    def is_active(self) -> bool:
        """Check if session is usable (active status + not expired + not closed)."""
        return self.status == "active" and not self.is_expired()

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "userId": self.user_id,
            "organizationId": self.organization_id,
            "courseId": self.course_id,
            "status": self.status,
            "scope": self.scope,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "closedAt": self.closed_at.isoformat() if self.closed_at else None,
            "lastAccessedAt": (
                self.last_accessed_at.isoformat()
                if self.last_accessed_at else None
            ),
        }


# ═══════════════════════════════════════════════════════════════════
# AI Proposals
# ═══════════════════════════════════════════════════════════════════

class AIProposalRecord(Base):
    """An AI-generated mutation proposal tied to a session.

    Proposals have a lifecycle: pending → applied | rejected | expired.
    They carry a base_hash for optimistic concurrency (staleness detection)
    and proposed_changes as a JSON diff/blueprint.
    """

    __tablename__ = "ai_proposals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str] = mapped_column(String(64), index=True)
    action_type: Mapped[str] = mapped_column(String(32))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    proposed_changes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    base_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confirmation_token_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
        comment="SHA-256 scope-bound hash of the confirmation token for destructive ops (US-AI-049)",
    )
    confirmation_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Expiry time for the confirmation token (US-AI-049)",
    )
    confirmation_ttl_override_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Per-operation-type TTL override in minutes (US-AI-049)",
    )
    before_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="Full before-state snapshot for destructive operations (US-AI-049)",
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def is_expired(self) -> bool:
        """Check if the proposal TTL has elapsed."""
        return datetime.utcnow() > self.expires_at

    def is_applied(self) -> bool:
        """Check if proposal has already been applied."""
        return self.status == "applied"

    def is_usable(self) -> bool:
        """Check if proposal can still be applied (pending + not expired)."""
        return self.status == "pending" and not self.is_expired()

    def to_dict(self) -> dict:
        return {
            "proposalId": self.proposal_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "organizationId": self.organization_id,
            "courseId": self.course_id,
            "actionType": self.action_type,
            "targetType": self.target_type,
            "targetId": self.target_id,
            "proposedChanges": self.proposed_changes,
            "status": self.status,
            "baseHash": self.base_hash,
            "confirmationTokenSha256": self.confirmation_token_sha256,
            "confirmationTokenExpiresAt": (
                self.confirmation_token_expires_at.isoformat()
                if self.confirmation_token_expires_at else None
            ),
            "confirmationTtlOverrideMinutes": self.confirmation_ttl_override_minutes,
            "beforeSnapshot": self.before_snapshot,
            "appliedAt": self.applied_at.isoformat() if self.applied_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "errorMessage": self.error_message,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


# ═══════════════════════════════════════════════════════════════════
# AI Confirmation Tokens
# ═══════════════════════════════════════════════════════════════════

class AIConfirmationTokenRecord(Base):
    """A one-time confirmation token for destructive AI operations.

    Tokens are bound to a proposal, session, and user. They can be
    consumed exactly once and have their own TTL (default 10 minutes).
    """

    __tablename__ = "ai_confirmation_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    proposal_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_proposals.proposal_id", ondelete="CASCADE"),
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    action_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def is_valid(self) -> bool:
        """Check if token is still usable (not consumed, not expired)."""
        return (
            not self.is_confirmed
            and datetime.utcnow() <= self.expires_at
        )

    def to_dict(self) -> dict:
        return {
            "tokenId": self.token_id,
            "proposalId": self.proposal_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "actionType": self.action_type,
            "description": self.description,
            "isConfirmed": self.is_confirmed,
            "confirmedAt": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


# ═══════════════════════════════════════════════════════════════════
# AI Audit Logs
# ═══════════════════════════════════════════════════════════════════

class AIAuditLogRecord(Base):
    """Append-only audit trail for all AI authoring actions.

    Every session create/revoke, proposal create/apply/reject, and
    confirmation event is recorded here. Queried by admin dashboards
    and compliance tools.
    """

    __tablename__ = "ai_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "auditId": self.audit_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "organizationId": self.organization_id,
            "courseId": self.course_id,
            "action": self.action,
            "targetType": self.target_type,
            "targetId": self.target_id,
            "details": self.details,
            "ipAddress": self.ip_address,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════════
# AI Outbox Events
# ═══════════════════════════════════════════════════════════════════

class AIOutboxEventRecord(Base):
    """Transactional outbox event for downstream consumers.

    Written in the same DB transaction as the domain mutation.
    A background publisher picks up pending events and delivers them
    to the event bus (Kafka, webhooks, etc.).
    """

    __tablename__ = "ai_outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "aggregateType": self.aggregate_type,
            "aggregateId": self.aggregate_id,
            "payload": self.payload,
            "status": self.status,
            "processedAt": self.processed_at.isoformat() if self.processed_at else None,
            "retryCount": self.retry_count,
            "errorMessage": self.error_message,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


# ═══════════════════════════════════════════════════════════════════
# AI Chat Turns
# ═══════════════════════════════════════════════════════════════════

class AIChatTurnRecord(Base):
    """A single turn in an AI chat conversation.

    Each turn records the user prompt, assistant response, model used,
    tool calls made, and token counts. Enables audit, debugging, and
    context window recovery.
    """

    __tablename__ = "ai_chat_turns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    turn_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "turnId": self.turn_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "role": self.role,
            "content": self.content,
            "toolCalls": self.tool_calls,
            "toolResults": self.tool_results,
            "tokensInput": self.tokens_input,
            "tokensOutput": self.tokens_output,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════════
# AI Idempotency Keys
# ═══════════════════════════════════════════════════════════════════

class AIIdempotencyKeyRecord(Base):
    """Idempotency key storage for safe retry of AI mutations.

    Stores the response of the first request so that retries with the
    same key return the cached result. Keys expire after a configurable
    TTL (default 24 hours).
    """

    __tablename__ = "ai_idempotency_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    def is_expired(self) -> bool:
        """Check if the idempotency key TTL has elapsed."""
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "idempotencyKey": self.idempotency_key,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "requestHash": self.request_hash,
            "responseStatus": self.response_status,
            "responseBody": self.response_body,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
        }


# ═══════════════════════════════════════════════════════════════════
# AI Ingestion Jobs (US-BKND-AI-016)
# ═══════════════════════════════════════════════════════════════════

class AIIngestionJobRecord(Base):
    """An AI document ingestion job for file upload and text extraction.

    ── Dual State Machine ──────────────────────────────────────────
    This record tracks TWO independent state machines:

    1. ``status`` (column) — Job lifecycle at the ingestion/router level:
       uploaded → analyzed → page_plan_ready → plan_approved → generated → completed
       Transitions are driven by router endpoints (propose-breakdown,
       review-plan, generate-course, apply).  Idempotent propose-breakdown
       can reset a terminal status back to page_plan_ready.

    2. ``source_metadata.generation_status`` (JSON key) — Generation progress
       inside CourseGenerator:
       null → generating → ready_for_review → completed
       Checked by apply_generated_course().  A re-upload with a different
       course_id resets completed → ready_for_review so the same generated
       content can be applied to a new course.

    These two fields CAN diverge — e.g. job.status="completed" while
    generation_status="ready_for_review" after a re-upload.  Downstream
    code must check the appropriate field for its concern:
    - Routers (propose-breakdown, review-plan) → job.status
    - CourseGenerator (start_generation, apply) → source_metadata.generation_status
    ─────────────────────────────────────────────────────────────────
    """

    __tablename__ = "ai_ingestion_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    file_name: Mapped[str] = mapped_column(String(500))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    detected_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    course_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    extracted_sections: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "jobId": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "fileName": self.file_name,
            "fileSize": self.file_size,
            "detectedType": self.detected_type,
            "courseId": self.course_id,
            "sessionId": self.session_id,
            "extractedSections": self.extracted_sections,
            "warnings": self.warnings,
            "errorMessage": self.error_message,
            "errorCode": self.error_code,
            "sourceMetadata": self.source_metadata,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
