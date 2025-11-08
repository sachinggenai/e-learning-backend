"""Repository layer for Template persistence (normalized templates/pages).

Handles CRUD plus order management and maintains a synchronized snapshot of
templates inside the parent CourseRecord.json_data["templates"].
"""
from __future__ import annotations
from typing import Sequence, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.persisted_course import CourseRecord, TemplateRecord


class TemplateNotFoundError(Exception):
    pass


class TemplateConflictError(Exception):
    pass


class TemplateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_course(self, course_id: int) -> CourseRecord:
        result = await self.session.execute(
            select(CourseRecord).where(CourseRecord.id == course_id)
        )
        course = result.scalar_one_or_none()
        if not course:
            raise TemplateNotFoundError("Parent course not found")
        return course

    async def _refresh_course_templates_snapshot(self, course: CourseRecord):
        # Load all templates for the course ordered by order_index
        result = await self.session.execute(
            select(TemplateRecord)
            .where(TemplateRecord.course_id == course.id)
            .order_by(TemplateRecord.order_index)
        )
        templates = result.scalars().all()
        snap = []
        for t in templates:
            snap.append(
                {
                    "id": t.template_uid,
                    "type": t.template_type,
                    "title": t.title,
                    "order": t.order_index,
                    "data": t.json_data,
                }
            )
        orig = course.json_data or {}
        new_data = {**orig, "templates": snap}
        course.json_data = new_data
        await self.session.flush()

    # CRUD ------------------------------------------------------------------
    async def list(self, course_id: int) -> Sequence[TemplateRecord]:
        await self._get_course(course_id)  # ensure exists
        result = await self.session.execute(
            select(TemplateRecord)
            .where(TemplateRecord.course_id == course_id)
            .order_by(TemplateRecord.order_index)
        )
        return result.scalars().all()

    async def get(self, course_id: int, template_id: int) -> TemplateRecord:
        result = await self.session.execute(
            select(TemplateRecord).where(
                TemplateRecord.course_id == course_id,
                TemplateRecord.id == template_id,
            )
        )
        tmpl = result.scalar_one_or_none()
        if not tmpl:
            raise TemplateNotFoundError
        return tmpl

    async def create(
        self,
        course_id: int,
        template_uid: str,
        template_type: str,
        title: str,
        data: dict,
        order: Optional[int] = None,
    ) -> TemplateRecord:
        course = await self._get_course(course_id)
        # Determine order: append if not provided
        if order is None:
            existing = await self.list(course_id)
            order = len(existing)
        record = TemplateRecord(
            course_id=course.id,
            template_uid=template_uid,
            template_type=template_type,
            title=title,
            order_index=order,
            json_data=data or {},
        )
        self.session.add(record)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise TemplateConflictError("Template already exists") from exc
        await self.session.refresh(record)
        # sync snapshot
        await self._refresh_course_templates_snapshot(course)
        await self.session.commit()
        return record

    async def update(
        self,
        course_id: int,
        template_id: int,
        title: Optional[str] = None,
        data: Optional[dict] = None,
        template_type: Optional[str] = None,
    ) -> TemplateRecord:
        tmpl = await self.get(course_id, template_id)
        course = await self._get_course(course_id)
        if title is not None:
            tmpl.title = title
        if data is not None:
            tmpl.json_data = data
        if template_type is not None:
            tmpl.template_type = template_type
        await self.session.commit()
        await self._refresh_course_templates_snapshot(course)
        await self.session.commit()
        return tmpl

    async def reorder(
        self, course_id: int, ordered_template_ids: List[int]
    ) -> Sequence[TemplateRecord]:
        course = await self._get_course(course_id)
        # Fetch templates
        result = await self.session.execute(
            select(TemplateRecord).where(
                TemplateRecord.course_id == course_id
            )
        )
        templates = {t.id: t for t in result.scalars().all()}
        if set(templates.keys()) != set(ordered_template_ids):
            raise TemplateConflictError(
                "Ordered IDs must match existing templates exactly"
            )
        for idx, tid in enumerate(ordered_template_ids):
            templates[tid].order_index = idx
        await self.session.commit()
        await self._refresh_course_templates_snapshot(course)
        await self.session.commit()
        # Return in new order
        ordered = [templates[tid] for tid in ordered_template_ids]
        return ordered

    async def delete(self, course_id: int, template_id: int) -> None:
        tmpl = await self.get(course_id, template_id)
        course = await self._get_course(course_id)
        await self.session.delete(tmpl)
        await self.session.commit()
        await self._refresh_course_templates_snapshot(course)
        await self.session.commit()
