"""Repository layer for Course persistence.

Provides an abstraction over direct SQLAlchemy session usage so that routers
and services remain thin and testable. Future additions (caching, soft delete,
multitenancy) can be centralized here.
"""
from __future__ import annotations
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.persisted_course import CourseRecord

class CourseNotFoundError(Exception):
    """Raised when a course record could not be located."""


class CourseConflictError(Exception):
    """Raised when attempting to create a course with an existing course_id."""


class CourseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # CREATE -----------------------------------------------------------------
    async def create(
        self,
        course_id: str,
        title: str,
        description: Optional[str],
        data: dict,
    ) -> CourseRecord:
        # Check conflict
        existing = await self.session.execute(
            select(CourseRecord).where(CourseRecord.course_id == course_id)
        )
        if existing.scalar_one_or_none():
            raise CourseConflictError("courseId already exists")

        record = CourseRecord(
            course_id=course_id,
            title=title,
            description=description,
            json_data=data or {},
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    # READ -------------------------------------------------------------------
    async def list(self) -> Sequence[CourseRecord]:
        result = await self.session.execute(select(CourseRecord))
        return result.scalars().all()

    async def get(self, pk: int) -> CourseRecord:
        result = await self.session.execute(
            select(CourseRecord).where(CourseRecord.id == pk)
        )
        record = result.scalar_one_or_none()
        if not record:
            raise CourseNotFoundError
        return record

    async def get_by_course_id(self, course_id: str) -> CourseRecord:
        result = await self.session.execute(
            select(CourseRecord).where(CourseRecord.course_id == course_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            raise CourseNotFoundError
        return record

    # UPDATE -----------------------------------------------------------------
    async def update_record(
        self,
        pk: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        data: Optional[dict] = None,
        status: Optional[str] = None,
    ) -> CourseRecord:
        record = await self.get(pk)
        if title is not None:
            record.title = title
        if description is not None:
            record.description = description
        if data is not None:
            record.json_data = data
        if status is not None:
            record.status = status
        await self.session.commit()
        await self.session.refresh(record)
        return record

    # DELETE -----------------------------------------------------------------
    async def delete_record(self, pk: int) -> None:
        record = await self.get(pk)
        await self.session.delete(record)
        await self.session.commit()
