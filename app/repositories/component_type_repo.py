"""Repository for ComponentType — the Component Type Registry.

Provides CRUD + filtering for component type definitions.
"""
from __future__ import annotations
from typing import Optional, List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.component_type import ComponentType


class ComponentTypeRepository:
    """DB access for component_types table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Queries ──────────────────────────────

    async def list(
        self,
        *,
        category: Optional[str] = None,
        scoring_enabled: Optional[bool] = None,
        is_active: Optional[bool] = True,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[List[ComponentType], int]:
        """Return paginated list + total count."""
        conditions = []
        if category:
            conditions.append(ComponentType.category == category)
        if scoring_enabled is not None:
            conditions.append(ComponentType.scoring_enabled == scoring_enabled)
        if is_active is not None:
            conditions.append(ComponentType.is_active == is_active)

        where = and_(*conditions) if conditions else True

        count_q = select(func.count()).select_from(ComponentType).where(where)
        total = (await self.session.execute(count_q)).scalar() or 0

        q = (
            select(ComponentType)
            .where(where)
            .order_by(ComponentType.sort_order, ComponentType.display_name)
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = (await self.session.execute(q)).scalars().all()
        return list(rows), total

    async def get_by_type_id(self, type_id: str) -> Optional[ComponentType]:
        q = select(ComponentType).where(ComponentType.type_id == type_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_categories(self) -> list[dict]:
        """Return distinct categories with component counts."""
        q = (
            select(ComponentType.category, func.count().label("cnt"))
            .where(ComponentType.is_active == True)  # noqa: E712
            .group_by(ComponentType.category)
            .order_by(ComponentType.category)
        )
        rows = (await self.session.execute(q)).all()
        return [{"categoryId": r[0], "componentCount": r[1]} for r in rows]

    async def search(
        self,
        *,
        q: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[List[ComponentType], int]:
        """Free-text search across display_name, description, tags."""
        conditions = [ComponentType.is_active == True]  # noqa: E712
        if category:
            conditions.append(ComponentType.category == category)
        if q:
            pattern = f"%{q}%"
            conditions.append(
                ComponentType.display_name.ilike(pattern)
                | ComponentType.description.ilike(pattern)
                | ComponentType.type_id.ilike(pattern)
            )

        where = and_(*conditions)
        count_q = select(func.count()).select_from(ComponentType).where(where)
        total = (await self.session.execute(count_q)).scalar() or 0

        stmt = (
            select(ComponentType)
            .where(where)
            .order_by(ComponentType.sort_order, ComponentType.display_name)
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    # ── Mutations ────────────────────────────

    async def create(self, ct: ComponentType) -> ComponentType:
        self.session.add(ct)
        await self.session.commit()
        await self.session.refresh(ct)
        return ct

    async def upsert(self, type_id: str, **kwargs) -> ComponentType:
        """Insert or update by type_id."""
        existing = await self.get_by_type_id(type_id)
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            await self.session.commit()
            await self.session.refresh(existing)
            return existing
        ct = ComponentType(type_id=type_id, **kwargs)
        self.session.add(ct)
        await self.session.commit()
        await self.session.refresh(ct)
        return ct

    async def bulk_upsert(self, items: list[dict]) -> int:
        """Upsert many component types. Returns count."""
        count = 0
        for item in items:
            type_id = item.pop("type_id", None) or item.pop("typeId", None)
            if type_id:
                await self.upsert(type_id, **item)
                count += 1
        return count
