"""Repository for TemplateType persistence.

Handles CRUD operations for template types (the reusable template definitions
shown in the template picker UI, not individual course templates).
"""
from __future__ import annotations
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.template_type import TemplateType


class TemplateTypeNotFoundError(Exception):
    """Raised when a template type could not be located."""


class TemplateTypeConflictError(Exception):
    """Raised when attempting to create a template type with an existing ID."""


class TemplateTypeRepository:
    """Repository for TemplateType data access."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # CREATE -----------------------------------------------------------------
    async def create(
        self,
        template_id: str,
        name: str,
        description: str,
        category: str,
        thumbnail: Optional[str] = None,
        estimated_duration: Optional[int] = None,
        rating: float = 0.0,
        usage_count: int = 0,
        can_be_page: bool = True,
        fields: Optional[dict] = None,
        is_active: bool = True,
    ) -> TemplateType:
        """Create a new template type."""
        # Check for conflicts
        existing = await self.session.execute(
            select(TemplateType).where(
                TemplateType.template_id == template_id
            )
        )
        if existing.scalar_one_or_none():
            raise TemplateTypeConflictError(
                f"Template type '{template_id}' already exists"
            )

        record = TemplateType(
            template_id=template_id,
            name=name,
            description=description,
            category=category,
            thumbnail=thumbnail,
            estimated_duration=estimated_duration,
            rating=rating,
            usage_count=usage_count,
            can_be_page=can_be_page,
            fields=fields or {},
            is_active=is_active,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    # READ -------------------------------------------------------------------
    async def list(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
    ) -> Sequence[TemplateType]:
        """List template types, optionally filtered by category."""
        query = select(TemplateType)

        if active_only:
            query = query.where(TemplateType.is_active == True)  # noqa: E712

        if category:
            query = query.where(TemplateType.category == category)

        result = await self.session.execute(
            query.order_by(TemplateType.rating.desc())
        )
        return result.scalars().all()

    async def get_by_id(self, template_type_id: int) -> TemplateType:
        """Get a template type by ID."""
        result = await self.session.execute(
            select(TemplateType).where(TemplateType.id == template_type_id)
        )
        tmpl = result.scalar_one_or_none()
        if not tmpl:
            raise TemplateTypeNotFoundError(
                f"Template type ID {template_type_id} not found"
            )
        return tmpl

    async def get_by_template_id(self, template_id: str) -> TemplateType:
        """Get a template type by template_id."""
        result = await self.session.execute(
            select(TemplateType).where(
                TemplateType.template_id == template_id
            )
        )
        tmpl = result.scalar_one_or_none()
        if not tmpl:
            raise TemplateTypeNotFoundError(
                f"Template type '{template_id}' not found"
            )
        return tmpl

    async def get_categories(self, active_only: bool = True) -> list[str]:
        """Get all unique categories."""
        query = select(TemplateType.category).distinct()

        if active_only:
            query = query.where(TemplateType.is_active == True)  # noqa: E712

        result = await self.session.execute(query)
        return sorted(result.scalars().all())

    # UPDATE -----------------------------------------------------------------
    async def update(
        self,
        template_type_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        rating: Optional[float] = None,
        usage_count: Optional[int] = None,
        fields: Optional[dict] = None,
        is_active: Optional[bool] = None,
    ) -> TemplateType:
        """Update a template type."""
        tmpl = await self.get_by_id(template_type_id)

        if name is not None:
            tmpl.name = name
        if description is not None:
            tmpl.description = description
        if rating is not None:
            tmpl.rating = rating
        if usage_count is not None:
            tmpl.usage_count = usage_count
        if fields is not None:
            tmpl.fields = fields
        if is_active is not None:
            tmpl.is_active = is_active

        await self.session.commit()
        await self.session.refresh(tmpl)
        return tmpl

    async def increment_usage(self, template_type_id: int) -> TemplateType:
        """Increment the usage count for a template type."""
        tmpl = await self.get_by_id(template_type_id)
        tmpl.usage_count += 1
        await self.session.commit()
        await self.session.refresh(tmpl)
        return tmpl

    # DELETE -----------------------------------------------------------------
    async def deactivate(self, template_type_id: int) -> None:
        """Deactivate a template type instead of deleting it."""
        tmpl = await self.get_by_id(template_type_id)
        tmpl.is_active = False
        await self.session.commit()

    async def delete(self, template_type_id: int) -> None:
        """Delete a template type (hard delete)."""
        tmpl = await self.get_by_id(template_type_id)
        await self.session.delete(tmpl)
        await self.session.commit()
