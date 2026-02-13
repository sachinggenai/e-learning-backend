"""Repository for PageRecord and ComponentRecord — page & component CRUD."""
from __future__ import annotations
from typing import Optional, List

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.page_component import PageRecord, ComponentRecord


class PageRepository:
    """DB access for pages table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_course(self, course_id: str) -> List[PageRecord]:
        q = (
            select(PageRecord)
            .where(PageRecord.course_id == course_id)
            .options(selectinload(PageRecord.components))
            .order_by(PageRecord.order_index)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get(self, page_id: str) -> Optional[PageRecord]:
        q = (
            select(PageRecord)
            .where(PageRecord.page_id == page_id)
            .options(selectinload(PageRecord.components))
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_by_course_and_page(
        self, course_id: str, page_id: str
    ) -> Optional[PageRecord]:
        q = (
            select(PageRecord)
            .where(PageRecord.course_id == course_id, PageRecord.page_id == page_id)
            .options(selectinload(PageRecord.components))
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def count_by_course(self, course_id: str) -> int:
        q = select(func.count()).select_from(PageRecord).where(
            PageRecord.course_id == course_id
        )
        return (await self.session.execute(q)).scalar() or 0

    async def create(self, page: PageRecord) -> PageRecord:
        self.session.add(page)
        await self.session.commit()
        await self.session.refresh(page)
        return page

    async def update(self, page: PageRecord) -> PageRecord:
        await self.session.commit()
        await self.session.refresh(page)
        return page

    async def delete(self, page: PageRecord) -> None:
        await self.session.delete(page)
        await self.session.commit()

    async def reorder(self, course_id: str, ordered_ids: List[str]) -> List[PageRecord]:
        pages = await self.list_by_course(course_id)
        id_to_page = {p.page_id: p for p in pages}
        for idx, pid in enumerate(ordered_ids):
            if pid in id_to_page:
                id_to_page[pid].order_index = idx
        await self.session.commit()
        return await self.list_by_course(course_id)


class ComponentRepository:
    """DB access for components table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_page(self, page_id: str) -> List[ComponentRecord]:
        q = (
            select(ComponentRecord)
            .where(ComponentRecord.page_id == page_id)
            .order_by(ComponentRecord.order_index)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get(self, component_id: str) -> Optional[ComponentRecord]:
        q = select(ComponentRecord).where(
            ComponentRecord.component_id == component_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_by_page_and_component(
        self, page_id: str, component_id: str
    ) -> Optional[ComponentRecord]:
        q = select(ComponentRecord).where(
            ComponentRecord.page_id == page_id,
            ComponentRecord.component_id == component_id,
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def count_by_page(self, page_id: str) -> int:
        q = select(func.count()).select_from(ComponentRecord).where(
            ComponentRecord.page_id == page_id
        )
        return (await self.session.execute(q)).scalar() or 0

    async def create(self, comp: ComponentRecord) -> ComponentRecord:
        self.session.add(comp)
        await self.session.commit()
        await self.session.refresh(comp)
        return comp

    async def update(self, comp: ComponentRecord) -> ComponentRecord:
        await self.session.commit()
        await self.session.refresh(comp)
        return comp

    async def delete(self, comp: ComponentRecord) -> None:
        await self.session.delete(comp)
        await self.session.commit()

    async def reorder(self, page_id: str, ordered_ids: List[str]) -> List[ComponentRecord]:
        comps = await self.list_by_page(page_id)
        id_to_comp = {c.component_id: c for c in comps}
        for idx, cid in enumerate(ordered_ids):
            if cid in id_to_comp:
                id_to_comp[cid].order_index = idx
        await self.session.commit()
        return await self.list_by_page(page_id)

    async def list_by_course(self, course_id: str) -> List[ComponentRecord]:
        """Get all components across all pages in a course."""
        q = (
            select(ComponentRecord)
            .join(PageRecord, ComponentRecord.page_id == PageRecord.page_id)
            .where(PageRecord.course_id == course_id)
            .order_by(PageRecord.order_index, ComponentRecord.order_index)
        )
        return list((await self.session.execute(q)).scalars().all())
