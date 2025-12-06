"""
Repository for Template Definitions

Async repository for CRUD operations on template definitions with caching
support.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from app.models.template_definition import TemplateDefinitionRecord
from app.models.template_schema import TemplateDefinition
import logging
import json

logger = logging.getLogger(__name__)


class TemplateDefinitionNotFoundError(Exception):
    """Raised when template definition not found."""
    pass


class TemplateDefinitionRepository:
    """Async repository for template definitions."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_type_key(self, type_key: str) -> TemplateDefinition:
        """
        Get template definition by type key.
        
        Args:
            type_key: Template type identifier
            
        Returns:
            TemplateDefinition object
            
        Raises:
            TemplateDefinitionNotFoundError: If definition not found
        """
        stmt = select(TemplateDefinitionRecord).where(
            TemplateDefinitionRecord.type_key == type_key
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record:
            raise TemplateDefinitionNotFoundError(
                f"Template definition not found for type: {type_key}"
            )
        
        # Parse JSON fields and return Pydantic model
        return TemplateDefinition(
            type_key=record.type_key,
            schema_signature=record.schema_signature,
            field_schema=json.loads(record.field_schema_json),
            render_config=json.loads(record.render_config_json),
            sanitize_rules=json.loads(record.sanitize_rules_json),
            scorm_behavior=json.loads(record.scorm_behavior_json),
            renderer_class=record.renderer_class,
            layout_version=record.layout_version,
            created_at=record.created_at,
            updated_at=record.updated_at
        )
    
    async def get_by_schema_signature(
        self, signature: str
    ) -> Optional[TemplateDefinition]:
        """Find definition by schema signature hash."""
        stmt = select(TemplateDefinitionRecord).where(
            TemplateDefinitionRecord.schema_signature == signature
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return TemplateDefinition(
            type_key=record.type_key,
            schema_signature=record.schema_signature,
            field_schema=json.loads(record.field_schema_json),
            render_config=json.loads(record.render_config_json),
            sanitize_rules=json.loads(record.sanitize_rules_json),
            scorm_behavior=json.loads(record.scorm_behavior_json),
            renderer_class=record.renderer_class,
            layout_version=record.layout_version
        )
    
    async def create(
        self, definition: TemplateDefinition
    ) -> TemplateDefinition:
        """
        Create new template definition.
        
        Args:
            definition: TemplateDefinition to persist
            
        Returns:
            Created TemplateDefinition with timestamps
        """
        record = TemplateDefinitionRecord(
            id=definition.type_key,  # Use type_key as primary key
            type_key=definition.type_key,
            schema_signature=definition.schema_signature,
            field_schema_json=json.dumps(
                [f.model_dump() for f in definition.field_schema]
            ),
            render_config_json=json.dumps(
                definition.render_config.model_dump()
            ),
            sanitize_rules_json=json.dumps(definition.sanitize_rules),
            scorm_behavior_json=json.dumps(
                definition.scorm_behavior.model_dump()
            ),
            renderer_class=definition.renderer_class,
            layout_version=definition.layout_version
        )
        
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        
        logger.info(f"Created template definition: {definition.type_key}")
        return await self.get_by_type_key(definition.type_key)
    
    async def list_all(self) -> List[TemplateDefinition]:
        """Get all template definitions."""
        stmt = select(TemplateDefinitionRecord).order_by(
            TemplateDefinitionRecord.template_type
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        
        return [
            TemplateDefinition(
                type_key=r.type_key,
                schema_signature=r.schema_signature,
                field_schema=json.loads(r.field_schema_json),
                render_config=json.loads(r.render_config_json),
                sanitize_rules=json.loads(r.sanitize_rules_json),
                scorm_behavior=json.loads(r.scorm_behavior_json),
                renderer_class=r.renderer_class,
                layout_version=r.layout_version
            )
            for r in records
        ]
    
    async def exists(self, type_key: str) -> bool:
        """Check if template definition exists."""
        stmt = select(TemplateDefinitionRecord.id).where(
            TemplateDefinitionRecord.type_key == type_key
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

