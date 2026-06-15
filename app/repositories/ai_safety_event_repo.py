"""Repository for AISafetyEvent — safety event persistence.

US-BKND-AI-025: Non-blocking safety event storage. Writes are
fire-and-forget (failures logged, never block the request pipeline).
"""

from __future__ import annotations

import logging
from typing import Optional, List

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_safety_event import AISafetyEvent

logger = logging.getLogger(__name__)


class AISafetyEventRepository:
    """Data access for ai_safety_events table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, record: AISafetyEvent) -> Optional[AISafetyEvent]:
        """Insert a safety event (fire-and-forget).

        Returns None if the write fails — safety events never block the
        request pipeline. Errors are logged for monitoring.
        """
        try:
            self.session.add(record)
            await self.session.commit()
            await self.session.refresh(record)
            return record
        except Exception:
            logger.exception(
                "Failed to write safety event — non-blocking"
            )
            await self.session.rollback()
            return None

    async def create_non_blocking(self, record: AISafetyEvent) -> None:
        """Fire-and-forget: best-effort write, never raises."""
        try:
            self.session.add(record)
            await self.session.commit()
        except Exception:
            logger.debug(
                "Safety event write skipped (non-blocking): %s",
                record.event_type,
            )
            await self.session.rollback()

    async def get(self, event_id: str) -> Optional[AISafetyEvent]:
        """Get a safety event by ID."""
        q = select(AISafetyEvent).where(AISafetyEvent.event_id == event_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def list_by_type(
        self,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AISafetyEvent]:
        """List safety events with optional filters."""
        q = select(AISafetyEvent)

        if event_type:
            q = q.where(AISafetyEvent.event_type == event_type)
        if severity:
            q = q.where(AISafetyEvent.severity == severity)
        if session_id:
            q = q.where(AISafetyEvent.session_id == session_id)
        if user_id:
            q = q.where(AISafetyEvent.user_id == user_id)

        q = q.order_by(desc(AISafetyEvent.created_at))
        q = q.offset(offset).limit(limit)

        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def count_by_type(
        self,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> int:
        """Count safety events matching filters."""
        from sqlalchemy import func

        q = select(func.count()).select_from(AISafetyEvent)
        if event_type:
            q = q.where(AISafetyEvent.event_type == event_type)
        if severity:
            q = q.where(AISafetyEvent.severity == severity)

        result = await self.session.execute(q)
        return result.scalar() or 0
