"""Repository for ThemeRecord — theme CRUD."""
from __future__ import annotations
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.theme import ThemeRecord


class ThemeRepository:
    """DB access for themes table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, *, is_preset: Optional[bool] = None) -> List[ThemeRecord]:
        q = select(ThemeRecord).order_by(ThemeRecord.name)
        if is_preset is not None:
            q = q.where(ThemeRecord.is_preset == is_preset)
        return list((await self.session.execute(q)).scalars().all())

    async def get(self, theme_id: str) -> Optional[ThemeRecord]:
        q = select(ThemeRecord).where(ThemeRecord.theme_id == theme_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[ThemeRecord]:
        q = select(ThemeRecord).where(ThemeRecord.name == name)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, theme: ThemeRecord) -> ThemeRecord:
        self.session.add(theme)
        await self.session.commit()
        await self.session.refresh(theme)
        return theme

    async def update(self, theme: ThemeRecord) -> ThemeRecord:
        await self.session.commit()
        await self.session.refresh(theme)
        return theme

    async def delete(self, theme: ThemeRecord) -> None:
        await self.session.delete(theme)
        await self.session.commit()
