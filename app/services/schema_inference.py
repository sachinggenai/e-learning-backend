"""
Schema Inference Engine for dynamically inferring template schemas from data.

Generates JSON schemas, render templates, and schema signatures for new template types.
"""

import json
import hashlib
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from jinja2 import Template as Jinja2Template

logger = logging.getLogger(__name__)


class SchemaInferenceEngine:
    """Infers schemas from extracted template data."""

    @staticmethod
    def compute_schema_signature(schema: Dict[str, Any]) -> str:
        """
        Compute deterministic SHA-256 hash of field schema.

        Args:
            schema: The schema dictionary

        Returns:
            SHA-256 hex digest
        """
        canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def infer_schema_from_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Infer JSON Schema from Python object.

        Args:
            data: Template data object

        Returns:
            Dictionary with schema information
        """
        if not isinstance(data, dict):
            return {"type": "unknown", "fields": []}

        fields = []

        for key, value in data.items():
            field_type = SchemaInferenceEngine._infer_type(value)
            fields.append({
                "name": key,
                "type": field_type,
                "required": True,
                "nullable": value is None
            })

        return {
            "type": "object",
            "fields": fields,
            "field_count": len(fields),
            "inferred_at": datetime.utcnow().isoformat()
        }

    @staticmethod
    def _infer_type(value: Any) -> str:
        """Map Python type to schema type string."""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "integer"
        elif isinstance(value, float):
            return "number"
        elif isinstance(value, str):
            # Check if it looks like a URL
            if value.startswith(("http://", "https://", "/")):
                return "url"
            elif "<" in value and ">" in value:
                return "html"
            else:
                return "text"
        elif isinstance(value, list):
            if value:
                item_types = set(
                    SchemaInferenceEngine._infer_type(item) for item in value
                )
                if len(item_types) == 1:
                    return f"array[{item_types.pop()}]"
            return "array"
        elif isinstance(value, dict):
            return "object"
        else:
            return "unknown"

    @staticmethod
    def generate_render_template(schema: Dict[str, Any], template_type: str) -> str:
        """
        Generate a default Jinja2 render template for a schema.

        Args:
            schema: Inferred schema
            template_type: Template type identifier

        Returns:
            Jinja2 template string
        """
        fields = schema.get("fields", [])

        if not fields:
            return (
                f"<div class='template-{template_type}'>"
                "<p>No data fields defined</p>"
                "</div>"
            )

        # Generate field renderers
        field_renders = []
        for field in fields:
            field_name = field.get("name", "field")
            field_type = field.get("type", "text")

            if field_type == "html":
                field_renders.append(f"  <div class='field-{field_name}'>{{{{ data.{field_name} | safe }}}}</div>")
            elif field_type == "url":
                field_renders.append(f"  <img src='{{{{ data.{field_name} }}}}' alt='{field_name}' class='media-{field_name}' />")
            elif field_type in ("array", "array[object]"):
                field_renders.append(
                    f"  <ul class='list-{field_name}'>\n"
                    f"    {{% for item in data.{field_name} %}}\n"
                    f"    <li>{{{{ item }}}}</li>\n"
                    f"    {{% endfor %}}\n"
                    f"  </ul>"
                )
            else:
                field_renders.append(f"  <div class='field-{field_name}'>{{{{ data.{field_name} }}}}</div>")

        template_str = (
            f"<div class='template template-{template_type}'>\n"
            f"  <div class='header'>{template_type.replace('-', ' ').title()}</div>\n"
            f"  <div class='content'>\n"
            + "\n".join(field_renders)
            + "\n  </div>\n"
            "</div>"
        )

        return template_str

    @staticmethod
    def generate_field_schema_json(schema: Dict[str, Any]) -> str:
        """Generate JSON-serialized field schema for DB storage."""
        field_schema = {
            "version": "1.0",
            "fields": schema.get("fields", []),
            "generated_at": datetime.utcnow().isoformat()
        }
        return json.dumps(field_schema)

    @staticmethod
    def generate_schema_json(schema: Dict[str, Any]) -> str:
        """Generate JSON-serialized schema for DB storage."""
        return json.dumps(schema)

    @staticmethod
    def infer_template_definition(
        template_data: Dict[str, Any],
        template_type: str,
        source_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Infer a complete template definition from template data.

        Args:
            template_data: The template data object
            template_type: Type identifier for the template
            source_metadata: Optional metadata about the source

        Returns:
            Dictionary ready for database insertion
        """
        schema = SchemaInferenceEngine.infer_schema_from_data(template_data)
        schema_signature = SchemaInferenceEngine.compute_schema_signature(schema)
        render_template_html = SchemaInferenceEngine.generate_render_template(
            schema, template_type
        )
        field_schema_json = SchemaInferenceEngine.generate_field_schema_json(schema)
        schema_json = SchemaInferenceEngine.generate_schema_json(schema)

        return {
            "template_type": template_type,
            "display_name": template_type.replace("-", " ").title(),
            "schema_signature": schema_signature,
            "render_template_html": render_template_html,
            "field_schema_json": field_schema_json,
            "schema_json": schema_json,
            "is_active": False,  # New definitions start as DRAFT
            "source_metadata": source_metadata or {},
            "created_at": datetime.utcnow().isoformat()
        }

    @staticmethod
    def validate_schema_match(
        schema1: Dict[str, Any],
        schema2: Dict[str, Any]
    ) -> bool:
        """
        Check if two schemas are functionally equivalent.

        Args:
            schema1: First schema
            schema2: Second schema

        Returns:
            True if schemas match (same signature)
        """
        sig1 = SchemaInferenceEngine.compute_schema_signature(schema1)
        sig2 = SchemaInferenceEngine.compute_schema_signature(schema2)
        return sig1 == sig2
