"""ORM model for AI safety events — prompt injection, PII, toxicity logs.

US-BKND-AI-025: Immutable safety event records for guardrail actions.
Written by input_guard and output_guard services. Stores only
sanitized/redacted content — never raw PII.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, Float, Index, DateTime, JSON

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AISafetyEvent(Base):
    """Immutable safety event record for guardrail actions."""

    __tablename__ = "ai_safety_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="system"
    )
    organization_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium"
    )

    input_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_length: Mapped[Optional[int]] = mapped_column(nullable=True)
    redacted_length: Mapped[Optional[int]] = mapped_column(nullable=True)

    rule_triggered: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    rule_category: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    audit_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    redacted_snippets: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_safety_type", "event_type"),
        Index("idx_safety_severity", "severity"),
        Index("idx_safety_rule", "rule_triggered"),
        Index("idx_safety_created", created_at.desc()),
        Index("idx_safety_session_id", "session_id"),
        Index("idx_safety_trace_id", "trace_id"),
    )

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "organizationId": self.organization_id,
            "eventType": self.event_type,
            "severity": self.severity,
            "inputSnippet": self.input_snippet,
            "outputSnippet": self.output_snippet,
            "originalLength": self.original_length,
            "redactedLength": self.redacted_length,
            "ruleTriggered": self.rule_triggered,
            "ruleCategory": self.rule_category,
            "confidence": self.confidence,
            "auditId": self.audit_id,
            "traceId": self.trace_id,
            "redactedSnippets": self.redacted_snippets,
            "createdAt": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
