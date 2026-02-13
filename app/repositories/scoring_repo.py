"""Repository for CourseScoringRecord — scoring config CRUD."""
from __future__ import annotations
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scoring import CourseScoringRecord


class ScoringRepository:
    """DB access for course_scoring table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_course(self, course_id: str) -> Optional[CourseScoringRecord]:
        q = select(CourseScoringRecord).where(
            CourseScoringRecord.course_id == course_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, record: CourseScoringRecord) -> CourseScoringRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update(self, record: CourseScoringRecord) -> CourseScoringRecord:
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def delete(self, record: CourseScoringRecord) -> None:
        await self.session.delete(record)
        await self.session.commit()

    async def upsert(self, course_id: str, **kwargs) -> CourseScoringRecord:
        """Insert or update scoring config for a course."""
        existing = await self.get_by_course(course_id)
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            await self.session.commit()
            await self.session.refresh(existing)
            return existing
        record = CourseScoringRecord(course_id=course_id, **kwargs)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record
