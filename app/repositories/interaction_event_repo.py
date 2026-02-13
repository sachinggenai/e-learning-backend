"""Repository for InteractionEventRecord — persisted interaction events."""
from __future__ import annotations
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interaction_event import InteractionEventRecord


class InteractionEventRepository:
    """DB access for interaction_events table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_course(
        self,
        course_id: str,
        *,
        learner_id: Optional[str] = None,
        interaction_type: Optional[str] = None,
        page_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[InteractionEventRecord]:
        q = select(InteractionEventRecord).where(
            InteractionEventRecord.course_id == course_id
        )
        if learner_id:
            q = q.where(InteractionEventRecord.learner_id == learner_id)
        if interaction_type:
            q = q.where(InteractionEventRecord.interaction_type == interaction_type)
        if page_id:
            q = q.where(InteractionEventRecord.page_id == page_id)
        q = q.order_by(InteractionEventRecord.created_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(q)).scalars().all())

    async def count_by_course(self, course_id: str) -> int:
        q = (
            select(func.count())
            .select_from(InteractionEventRecord)
            .where(InteractionEventRecord.course_id == course_id)
        )
        return (await self.session.execute(q)).scalar() or 0

    async def create(self, event: InteractionEventRecord) -> InteractionEventRecord:
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def get(self, event_id: str) -> Optional[InteractionEventRecord]:
        q = select(InteractionEventRecord).where(
            InteractionEventRecord.event_id == event_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def aggregate_by_type(self, course_id: str) -> List[dict]:
        """Return interaction counts grouped by type."""
        q = (
            select(
                InteractionEventRecord.interaction_type,
                func.count().label("count"),
            )
            .where(InteractionEventRecord.course_id == course_id)
            .group_by(InteractionEventRecord.interaction_type)
            .order_by(func.count().desc())
        )
        rows = (await self.session.execute(q)).all()
        return [{"interactionType": r[0], "count": r[1]} for r in rows]
