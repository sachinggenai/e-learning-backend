from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.persisted_course import TemplateDefinition
from .base import BaseTemplateRenderer
from .dynamic import DynamicTemplateRenderer


class TemplateRegistry:
    """Registry for template renderers."""

    _renderers: Dict[str, BaseTemplateRenderer] = {}

    @classmethod
    def register(cls, renderer: BaseTemplateRenderer):
        """Register a renderer for a template type."""
        cls._renderers[renderer.template_type] = renderer

    @classmethod
    def get_renderer(
        cls, template_type: str
    ) -> Optional[BaseTemplateRenderer]:
        """Get a renderer for a template type."""
        return cls._renderers.get(template_type)

    @classmethod
    async def load_definitions(cls, session: AsyncSession):
        """Load all active template definitions from DB and register."""
        result = await session.execute(
            select(TemplateDefinition).where(
                TemplateDefinition.is_active.is_(True)
            )
        )
        definitions = result.scalars().all()

        for definition in definitions:
            renderer = DynamicTemplateRenderer(definition)
            cls.register(renderer)
