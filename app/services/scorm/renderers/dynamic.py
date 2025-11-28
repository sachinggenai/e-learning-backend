from typing import Dict, Any, List
from jinja2 import Template
from .base import BaseTemplateRenderer
from app.models.persisted_course import TemplateDefinition
import jsonschema


class DynamicTemplateRenderer(BaseTemplateRenderer):
    """Renderer that uses database definitions and Jinja2 templates."""

    def __init__(self, definition: TemplateDefinition):
        super().__init__(definition.type_id)
        self.definition = definition
        self.template = Template(definition.render_template)

    async def validate(self, data: Dict[str, Any]) -> bool:
        try:
            jsonschema.validate(
                instance=data, schema=self.definition.schema_definition
            )
            return True
        except jsonschema.ValidationError:
            return False

    async def render(
        self, data: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        return self.template.render(data=data, **context)

    async def get_assets(self, data: Dict[str, Any]) -> List[str]:
        return self.definition.default_assets
