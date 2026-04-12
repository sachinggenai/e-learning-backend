"""
Repository for Template Definitions

Async repository for CRUD operations on template definitions with caching
support.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List, Dict, Any
from app.models.persisted_course import TemplateDefinition as TemplateDefinitionRecord
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

    def _coerce_schema_json(self, record: TemplateDefinitionRecord) -> Dict[str, Any]:
        """Normalize schema_json into a dictionary payload."""
        raw = record.schema_json
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {}

    def _derive_field_schema(self, schema_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build FieldSchema-compatible entries from stored schema_json."""
        # Newer shape may already contain canonical field_schema entries.
        if isinstance(schema_payload.get("field_schema"), list):
            return schema_payload["field_schema"]

        inferred = schema_payload.get("fields", [])
        field_schema: List[Dict[str, Any]] = []
        if isinstance(inferred, list):
            for item in inferred:
                if not isinstance(item, dict):
                    continue
                raw_type = str(item.get("type", "text"))
                type_map = {
                    "integer": "number",
                    "array": "list",
                    "array[object]": "list",
                    "url": "text",
                    "null": "text",
                    "unknown": "text",
                }
                field_type = type_map.get(raw_type, raw_type)
                if field_type not in {"text", "html", "boolean", "number", "list", "object"}:
                    field_type = "text"
                sanitize_strategy = "html" if field_type == "html" else "text"
                field_schema.append({
                    "name": str(item.get("name", "field")),
                    "type": field_type,
                    "sanitize_strategy": sanitize_strategy,
                    "required": bool(item.get("required", True)),
                    "nested_schema": None,
                })
        return field_schema

    def _to_definition(self, record: TemplateDefinitionRecord) -> TemplateDefinition:
        """Convert ORM row into Pydantic TemplateDefinition model."""
        schema_payload = self._coerce_schema_json(record)
        field_schema = self._derive_field_schema(schema_payload)
        sanitize_rules = schema_payload.get("sanitize_rules")
        if not isinstance(sanitize_rules, dict):
            sanitize_rules = {
                fs["name"]: fs.get("sanitize_strategy", "text")
                for fs in field_schema
            }

        render_config = schema_payload.get("render_config")
        if not isinstance(render_config, dict):
            type_key = record.template_type
            component_type = "custom"
            if "mcq" in type_key:
                component_type = "mcq"
            elif "video" in type_key:
                component_type = "video"
            elif any(fs.get("type") == "html" for fs in field_schema):
                component_type = "html"
            render_config = {
                "component_type": component_type,
                "html_template": record.render_template_html,
                "nested_fields": None,
                "validation_rules": None,
            }

        scorm_behavior = schema_payload.get("scorm_behavior")
        if not isinstance(scorm_behavior, dict):
            scorm_behavior = {
                "interaction_type": "choice" if "mcq" in record.template_type else "none",
                "reports_score": "mcq" in record.template_type,
                "objective_per_question": False,
                "completion_threshold": None,
            }

        renderer_class = schema_payload.get(
            "renderer_class",
            "app.services.scorm.renderers.dynamic.DynamicTemplateRenderer",
        )
        layout_version = schema_payload.get("layout_version", 1)

        return TemplateDefinition(
            type_key=record.template_type,
            schema_signature=record.schema_signature,
            field_schema=field_schema,
            render_config=render_config,
            sanitize_rules=sanitize_rules,
            scorm_behavior=scorm_behavior,
            renderer_class=renderer_class,
            layout_version=int(layout_version),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
    
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
            TemplateDefinitionRecord.template_type == type_key
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record:
            raise TemplateDefinitionNotFoundError(
                f"Template definition not found for type: {type_key}"
            )
        
        return self._to_definition(record)
    
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
        
        return self._to_definition(record)
    
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
        schema_payload = {
            "field_schema": [f.model_dump() for f in definition.field_schema],
            "render_config": definition.render_config.model_dump(),
            "sanitize_rules": definition.sanitize_rules,
            "scorm_behavior": definition.scorm_behavior.model_dump(),
            "renderer_class": definition.renderer_class,
            "layout_version": definition.layout_version,
        }

        record = TemplateDefinitionRecord(
            template_type=definition.type_key,
            display_name=definition.type_key.replace("-", " ").title(),
            schema_signature=definition.schema_signature,
            render_template_html=(
                definition.render_config.html_template
                or "<div>{{ data }}</div>"
            ),
            schema_json=schema_payload,
            is_active=True,
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
        
        return [self._to_definition(r) for r in records]
    
    async def exists(self, type_key: str) -> bool:
        """Check if template definition exists."""
        stmt = select(TemplateDefinitionRecord.id).where(
            TemplateDefinitionRecord.template_type == type_key
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

