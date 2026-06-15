"""Repository for AIProposalRecord — AI proposal persistence.

Follows the standard repository pattern (AsyncSession constructor,
Optional return for not-found, explicit commit+refresh).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIProposalRecord


class AIProposalRepository:
    """Data access for ai_proposals table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, proposal_id: str) -> Optional[AIProposalRecord]:
        """Get a proposal by its string UUID."""
        q = select(AIProposalRecord).where(
            AIProposalRecord.proposal_id == proposal_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def list_by_session(self, session_id: str) -> List[AIProposalRecord]:
        """List all proposals for a session, newest first."""
        q = (
            select(AIProposalRecord)
            .where(AIProposalRecord.session_id == session_id)
            .order_by(AIProposalRecord.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def list_by_course(
        self, course_id: str, *, status: Optional[str] = None
    ) -> List[AIProposalRecord]:
        """List proposals for a course, optionally filtered by status."""
        q = (
            select(AIProposalRecord)
            .where(AIProposalRecord.course_id == course_id)
        )
        if status:
            q = q.where(AIProposalRecord.status == status)
        q = q.order_by(AIProposalRecord.created_at.desc())
        return list((await self.session.execute(q)).scalars().all())

    async def list_pending(self) -> List[AIProposalRecord]:
        """List all pending (non-expired) proposals."""
        now = datetime.utcnow()
        q = select(AIProposalRecord).where(
            AIProposalRecord.status == "pending",
            AIProposalRecord.expires_at > now,
        )
        return list((await self.session.execute(q)).scalars().all())

    async def create(self, record: AIProposalRecord) -> AIProposalRecord:
        """Insert a new proposal record."""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update(self, record: AIProposalRecord) -> AIProposalRecord:
        """Persist changes to an existing proposal record."""
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def expire_stale(self) -> int:
        """Mark expired pending proposals as 'expired'. Returns count."""
        now = datetime.utcnow()
        q = select(AIProposalRecord).where(
            AIProposalRecord.status == "pending",
            AIProposalRecord.expires_at <= now,
        )
        result = await self.session.execute(q)
        stale = list(result.scalars().all())
        for p in stale:
            p.status = "expired"
        if stale:
            await self.session.commit()
        return len(stale)

    async def mark_stale(self, proposal_id: str) -> Optional[AIProposalRecord]:
        """Mark a proposal as stale (base hash mismatch)."""
        record = await self.get(proposal_id)
        if record is None:
            return None
        record.status = "expired"
        record.error_message = "Base hash mismatch — resource changed since proposal created"
        await self.session.commit()
        await self.session.refresh(record)
        return record
