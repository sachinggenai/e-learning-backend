"""
Data-Driven Sanitization Engine

Uses template definitions to determine how to sanitize each field.
NO HARDCODED TEMPLATE LOGIC.
"""
from typing import Any, Dict, Optional
from app.services.scorm.registries import registry
import logging
import html

logger = logging.getLogger(__name__)

# Import existing sanitization if BeautifulSoup available
try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False


class DynamicSanitizer:
    """
    Data-driven sanitization engine.
    Uses template definitions to determine how to sanitize each field.
    """

    def __init__(self):
        self.registry = registry

    async def sanitize_template_data(
        self,
        type_key: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sanitize template data based on its registered definition.

        Args:
            type_key: Template type identifier
            data: Raw template data

        Returns:
            Sanitized data dictionary

        Raises:
            ValueError: If template not registered or data invalid
        """
        # Check if template is registered
        if not await self.registry.exists(type_key):
            logger.warning(
                f"Template type '{type_key}' not registered, "
                "using generic sanitization"
            )
            return self._generic_sanitize(data)

        # Get template definition
        definition = await self.registry.get(type_key)

        # Sanitize according to field schema
        sanitized = {}
        for field in definition.field_schema:
            if field.name not in data:
                if field.required:
                    raise ValueError(
                        f"Required field '{field.name}' missing in "
                        f"{type_key} data"
                    )
                continue

            value = data[field.name]
            strategy = definition.sanitize_rules.get(
                field.name,
                field.sanitize_strategy
            )

            sanitized[field.name] = await self._sanitize_field(
                value,
                strategy,
                field.nested_schema
            )

        # Include any extra fields not in schema (for flexibility)
        for key in data:
            if key not in sanitized:
                sanitized[key] = self._sanitize_text(data[key])

        return sanitized

    async def _sanitize_field(
        self,
        value: Any,
        strategy: str,
        nested_schema: Optional[Dict] = None
    ) -> Any:
        """Sanitize a single field based on strategy."""

        if strategy == "none":
            # Preserve as-is (for booleans, numbers)
            return value

        elif strategy == "text":
            return self._sanitize_text(value)

        elif strategy == "html":
            return self._sanitize_html(value)

        elif strategy == "preserve_structure":
            # For complex nested structures (MCQ questions, etc.)
            return await self._sanitize_nested(value, nested_schema)

        else:
            logger.warning(
                f"Unknown sanitize strategy '{strategy}', using text"
            )
            return self._sanitize_text(value)

    async def _sanitize_nested(
        self,
        data: Any,
        schema: Optional[Dict]
    ) -> Any:
        """
        Recursively sanitize nested structures based on schema.
        Handles lists, objects, and nested templates.
        """
        if not schema:
            return self._generic_sanitize(data)

        if schema.get("type") == "list" and isinstance(data, list):
            item_schema = schema.get("item_schema", {})
            return [
                await self._sanitize_item(item, item_schema)
                for item in data
            ]

        elif isinstance(data, dict):
            return await self._sanitize_item(data, schema)

        return data

    async def _sanitize_item(self, item: Any, schema: Dict) -> Any:
        """Sanitize a single item based on its schema."""
        if not isinstance(item, dict):
            return item

        sanitized = {}
        for key, value in item.items():
            if key not in schema:
                # Keep unknown fields but sanitize as text
                if isinstance(value, str):
                    sanitized[key] = self._sanitize_text(value)
                else:
                    sanitized[key] = value
                continue

            field_spec = schema[key]
            field_type = field_spec.get("type")
            sanitize_strategy = field_spec.get("sanitize", "text")

            if sanitize_strategy == "none":
                sanitized[key] = value
            elif sanitize_strategy == "text":
                sanitized[key] = (
                    self._sanitize_text(value)
                    if isinstance(value, str)
                    else value
                )
            elif sanitize_strategy == "html":
                sanitized[key] = (
                    self._sanitize_html(value)
                    if isinstance(value, str)
                    else value
                )
            elif field_type == "list":
                sanitized[key] = await self._sanitize_nested(
                    value, field_spec
                )
            else:
                sanitized[key] = value

        return sanitized

    def _sanitize_text(self, text: Any) -> str:
        """Basic text sanitization."""
        if not text:
            return ""
        return html.escape(str(text))

    def _sanitize_html(self, html_content: str) -> str:
        """HTML sanitization with BeautifulSoup or fallback."""
        if not html_content or not isinstance(html_content, str):
            return ""

        if not HAS_BEAUTIFULSOUP:
            logger.warning(
                "BeautifulSoup not available, using text sanitization"
            )
            return self._sanitize_text(html_content)

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Define allowed tags
            allowed_tags = {
                'p', 'br', 'strong', 'b', 'em', 'i', 'u',
                'h1', 'h2', 'h3', 'ul', 'ol', 'li', 'span', 'div'
            }

            # Remove dangerous tags
            for tag in soup.find_all():
                if tag.name in ['script', 'style', 'iframe']:
                    tag.decompose()
                    continue

                # Remove event handlers
                for attr in list(tag.attrs.keys()):
                    if attr.startswith('on'):
                        del tag[attr]

                if tag.name not in allowed_tags:
                    tag.unwrap()

            return str(soup)

        except Exception as e:
            logger.error(f"HTML sanitization failed: {e}")
            return self._sanitize_text(html_content)

    def _generic_sanitize(self, data: Any) -> Any:
        """Fallback for unregistered types."""
        if isinstance(data, dict):
            return {
                k: (
                    self._sanitize_text(v) if isinstance(v, str) else v
                )
                for k, v in data.items()
            }
        return data
