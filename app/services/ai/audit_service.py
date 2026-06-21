"""Audit logging service.

Append-only audit trail for all AI authoring actions. Every session
create/revoke, proposal create/apply/reject, and confirmation event
is recorded for compliance, debugging, and analytics.

TODOs by story:
    US-BKND-AI-020: Admin audit query endpoint with pagination.
    US-BKND-AI-021: Rate limit headers and rollout gates.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_audit_repo import AIAuditRepository
from app.models.ai_models import AIAuditLogRecord

logger = logging.getLogger("ai_authoring")


class AIAuditService:
    """Append-only audit logging for AI authoring operations."""

    # Standardized action type constants
    ACTION_SESSION_CREATED = "session.created"
    ACTION_SESSION_REVOKED = "session.revoked"
    ACTION_PROPOSAL_CREATED = "proposal.created"
    ACTION_PROPOSAL_APPLIED = "proposal.applied"
    ACTION_PROPOSAL_REJECTED = "proposal.rejected"
    ACTION_PROPOSAL_EXPIRED = "proposal.expired"
    ACTION_CONFIRMATION_CREATED = "confirmation.created"
    ACTION_CONFIRMATION_CONFIRMED = "confirmation.confirmed"
    ACTION_CHAT_TURN = "chat.turn"
    ACTION_SIMILAR_COURSE_RETRIEVAL = "similar_course.retrieval"

    def __init__(self, db: AsyncSession):
        self.repo = AIAuditRepository(db)

    async def log(
        self,
        session_id: Optional[str],
        user_id: str,
        organization_id: str,
        course_id: str,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> AIAuditLogRecord:
        """Write an audit log entry for an AI action.

        Args:
            session_id: The AI session (None for actions outside a session).
            user_id: The authenticated user who initiated the action.
            organization_id: The user's organization/tenant.
            course_id: The course being operated on.
            action: One of ACTION_* constants (e.g. "proposal.applied").
            target_type: "page", "component", "course", etc.
            target_id: The UUID of the affected resource.
            details: Arbitrary structured context (proposal IDs, model info).
            ip_address: Client IP for compliance.
        """
        now = datetime.utcnow()
        record = AIAuditLogRecord(
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            course_id=course_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip_address=ip_address,
            created_at=now,
        )
        created = await self.repo.create(record)
        logger.debug(
            "Audit: %s by user=%s on course=%s",
            action, user_id[:8], course_id[:8],
        )
        return created

    async def list_by_session(
        self, session_id: str
    ) -> List[AIAuditLogRecord]:
        """Get all audit entries for a session."""
        return await self.repo.list_by_session(session_id)

    async def list_by_course(
        self, course_id: str
    ) -> List[AIAuditLogRecord]:
        """Get all audit entries for a course."""
        return await self.repo.list_by_course(course_id)

    async def list_by_user(
        self, user_id: str, *, limit: int = 100
    ) -> List[AIAuditLogRecord]:
        """Get recent audit entries for a user."""
        return await self.repo.list_by_user(user_id, limit=limit)
