"""Repository for AISessionRecord — AI authoring session persistence.

Follows the standard repository pattern (AsyncSession constructor,
Optional return for not-found, explicit commit+refresh).

Updated for US-BKND-AI-006: added count_active_by_user, close_session,
list_active_by_user, and get_active_by_user_and_course.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AISessionRecord


class AISessionRepository:
    """Data access for ai_sessions table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, session_id: str) -> Optional[AISessionRecord]:
        """Get a session by its string UUID, regardless of status."""
        q = select(AISessionRecord).where(
            AISessionRecord.session_id == session_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_active(self, session_id: str) -> Optional[AISessionRecord]:
        """Get a session that is active and not expired."""
        now = datetime.utcnow()
        q = select(AISessionRecord).where(
            AISessionRecord.session_id == session_id,
            AISessionRecord.status == "active",
            AISessionRecord.expires_at > now,
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> List[AISessionRecord]:
        """List all sessions for a user, newest first."""
        q = (
            select(AISessionRecord)
            .where(AISessionRecord.user_id == user_id)
            .order_by(AISessionRecord.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def list_active_by_user(self, user_id: str) -> List[AISessionRecord]:
        """List all active (non-expired, non-closed) sessions for a user."""
        now = datetime.utcnow()
        q = (
            select(AISessionRecord)
            .where(
                AISessionRecord.user_id == user_id,
                AISessionRecord.status == "active",
                AISessionRecord.expires_at > now,
            )
            .order_by(AISessionRecord.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def list_by_course(self, course_id: str) -> List[AISessionRecord]:
        """List all sessions for a course, newest first."""
        q = (
            select(AISessionRecord)
            .where(AISessionRecord.course_id == course_id)
            .order_by(AISessionRecord.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def create(self, record: AISessionRecord) -> AISessionRecord:
        """Insert a new session record."""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update(self, record: AISessionRecord) -> AISessionRecord:
        """Persist changes to an existing session record."""
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def count_active_by_user(self, user_id: str) -> int:
        """Count active (non-expired, non-closed) sessions for a user."""
        now = datetime.utcnow()
        q = select(func.count()).select_from(AISessionRecord).where(
            AISessionRecord.user_id == user_id,
            AISessionRecord.status == "active",
            AISessionRecord.expires_at > now,
        )
        result = await self.session.execute(q)
        return result.scalar() or 0

    async def get_active_by_user_and_course(
        self, user_id: str, course_id: str
    ) -> Optional[AISessionRecord]:
        """Get an active session for a specific user+course combination."""
        now = datetime.utcnow()
        q = select(AISessionRecord).where(
            AISessionRecord.user_id == user_id,
            AISessionRecord.course_id == course_id,
            AISessionRecord.status == "active",
            AISessionRecord.expires_at > now,
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def revoke(self, session_id: str) -> Optional[AISessionRecord]:
        """Revoke a session by ID. Returns the updated record or None."""
        record = await self.get(session_id)
        if record is None:
            return None
        record.status = "revoked"
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def close_session(self, session_id: str) -> Optional[AISessionRecord]:
        """Soft-delete (close) a session by setting status='closed' and
        recording closed_at. Returns the updated record or None."""
        record = await self.get(session_id)
        if record is None:
            return None
        now = datetime.utcnow()
        record.status = "closed"
        record.closed_at = now
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def expire_stale(self) -> int:
        """Mark all active-but-expired sessions as 'expired'. Returns count."""
        now = datetime.utcnow()
        q = select(AISessionRecord).where(
            AISessionRecord.status == "active",
            AISessionRecord.expires_at <= now,
        )
        result = await self.session.execute(q)
        stale = list(result.scalars().all())
        for s in stale:
            s.status = "expired"
        if stale:
            await self.session.commit()
        return len(stale)

    async def touch(self, session_id: str) -> None:
        """Update last_accessed_at for a session."""
        now = datetime.utcnow()
        record = await self.get(session_id)
        if record:
            record.last_accessed_at = now
            await self.session.commit()
