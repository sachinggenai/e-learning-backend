"""Repository for AIAuditLogRecord — audit log persistence.

Follows the standard repository pattern (AsyncSession constructor,
explicit commit+refresh). Audit logs are append-only.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIAuditLogRecord


class AIAuditRepository:
    """Data access for ai_audit_logs table (append-only)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, record: AIAuditLogRecord) -> AIAuditLogRecord:
        """Insert a new audit log entry."""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get(self, audit_id: str) -> Optional[AIAuditLogRecord]:
        """Get a single audit entry by ID."""
        q = select(AIAuditLogRecord).where(
            AIAuditLogRecord.audit_id == audit_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def list_by_session(self, session_id: str) -> List[AIAuditLogRecord]:
        """List all audit entries for a session, newest first."""
        q = (
            select(AIAuditLogRecord)
            .where(AIAuditLogRecord.session_id == session_id)
            .order_by(AIAuditLogRecord.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def list_by_course(self, course_id: str) -> List[AIAuditLogRecord]:
        """List all audit entries for a course, newest first."""
        q = (
            select(AIAuditLogRecord)
            .where(AIAuditLogRecord.course_id == course_id)
            .order_by(AIAuditLogRecord.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def list_by_user(
        self, user_id: str, *, limit: int = 100
    ) -> List[AIAuditLogRecord]:
        """List audit entries for a user, newest first."""
        q = (
            select(AIAuditLogRecord)
            .where(AIAuditLogRecord.user_id == user_id)
            .order_by(AIAuditLogRecord.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def list_by_action(
        self, action: str, *, limit: int = 100
    ) -> List[AIAuditLogRecord]:
        """List audit entries by action type, newest first."""
        q = (
            select(AIAuditLogRecord)
            .where(AIAuditLogRecord.action == action)
            .order_by(AIAuditLogRecord.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(q)).scalars().all())
