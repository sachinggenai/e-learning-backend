"""Repository for AIChatTurnRecord — chat turn persistence.

Follows the standard repository pattern (AsyncSession constructor,
explicit commit+refresh).
"""

from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIChatTurnRecord


class AIChatTurnRepository:
    """Data access for ai_chat_turns table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, record: AIChatTurnRecord) -> AIChatTurnRecord:
        """Insert a new chat turn record."""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list_by_session(
        self, session_id: str
    ) -> List[AIChatTurnRecord]:
        """List all chat turns for a session in chronological order."""
        q = (
            select(AIChatTurnRecord)
            .where(AIChatTurnRecord.session_id == session_id)
            .order_by(AIChatTurnRecord.created_at.asc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def count_by_session(self, session_id: str) -> int:
        """Count total turns in a session."""
        q = select(AIChatTurnRecord).where(
            AIChatTurnRecord.session_id == session_id
        )
        result = await self.session.execute(q)
        return len(result.scalars().all())
