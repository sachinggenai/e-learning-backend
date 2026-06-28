"""AI Template Contracts Service.

Wraps the existing template_definitions table to produce AI-facing
template contracts with JSON Schema definitions and business rules.

Each template type has a canonical contract that specifies:
- JSON Schema: the exact shape of valid template data
- Business rules: cross-field constraints (min/max items, score ranges)
- Schema signature: SHA-256 hash for version detection

Reuses existing infrastructure:
- template_definitions table (TemplateDefinition ORM) for schemas + signatures
- schema_inference.compute_schema_signature() for hash computation

TODOs by story:
    US-BKND-AI-007: Use contracts in AI session context window builder.
    US-BKND-AI-008: Add contract version to validation results.
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persisted_course import TemplateDefinition as TemplateDefinitionRecord
from app.services.schema_inference import SchemaInferenceEngine

logger = logging.getLogger("ai_authoring")

# ═══════════════════════════════════════════════════════════════════
# Business Rules for the 5 canonical template types
# ═══════════════════════════════════════════════════════════════════

BUSINESS_RULES: Dict[str, Dict[str, Any]] = {
    "text-content": {
        "required_fields": ["title", "content"],
        "optional_fields": ["key_points"],
        "max_length": {"title": 200},
        "constraints": {},
    },
    "tabs": {
        "required_fields": ["title", "tabs"],
        "optional_fields": [],
        "max_length": {"title": 200, "tabs[].title": 50},
        "constraints": {
            "tabs": {"min_items": 2, "max_items": 6},
        },
    },
    "accordion": {
        "required_fields": ["title", "items"],
        "optional_fields": [],
        "max_length": {"title": 200, "items[].title": 100},
        "constraints": {
            "items": {"min_items": 2, "max_items": 20},
        },
    },
    "click-reveal": {
        "required_fields": ["title", "items"],
        "optional_fields": [],
        "max_length": {"title": 200, "items[].title": 100},
        "constraints": {
            "items": {"min_items": 2, "max_items": 10},
        },
    },
    "final-assessment": {
        "required_fields": ["title", "passing_score", "questions"],
        "optional_fields": [],
        "max_length": {"title": 200},
        "constraints": {
            "passing_score": {"min": 0, "max": 100},
            "questions": {"min_items": 3, "max_items": 50},
        },
    },
}

# ═══════════════════════════════════════════════════════════════════
# Default JSON Schemas (fallback when DB has no record)
# ═══════════════════════════════════════════════════════════════════

_FALLBACK_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "text-content": {
        "type": "object",
        "required": ["title", "content"],
        "properties": {
            "title": {"type": "string", "maxLength": 200},
            "content": {"type": "string"},
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },
    "tabs": {
        "type": "object",
        "required": ["title", "tabs"],
        "properties": {
            "title": {"type": "string", "maxLength": 200},
            "tabs": {
                "type": "array",
                "minItems": 2,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "required": ["title", "content"],
                    "properties": {
                        "title": {"type": "string", "maxLength": 50},
                        "content": {"type": "string"},
                        "icon": {"type": "string"},
                    },
                },
            },
        },
    },
    "accordion": {
        "type": "object",
        "required": ["title", "items"],
        "properties": {
            "title": {"type": "string", "maxLength": 200},
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "required": ["title", "content"],
                    "properties": {
                        "title": {"type": "string", "maxLength": 100},
                        "content": {"type": "string"},
                    },
                },
            },
        },
    },
    "click-reveal": {
        "type": "object",
        "required": ["title", "items"],
        "properties": {
            "title": {"type": "string", "maxLength": 200},
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "required": ["title", "content"],
                    "properties": {
                        "title": {"type": "string", "maxLength": 100},
                        "content": {"type": "string"},
                    },
                },
            },
        },
    },
    "final-assessment": {
        "type": "object",
        "required": ["title", "passing_score", "questions"],
        "properties": {
            "title": {"type": "string", "maxLength": 200},
            "passing_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "questions": {
                "type": "array",
                "minItems": 3,
                "maxItems": 50,
                "items": {
                    "type": "object",
                    "required": ["question", "options", "correctAnswer"],
                    "properties": {
                        "question": {"type": "string"},
                        "options": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 10,
                            "items": {
                                "type": "object",
                                "required": ["id", "text"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "text": {"type": "string"},
                                    "isCorrect": {"type": "boolean"},
                                },
                            },
                        },
                        "correctAnswer": {"type": "string"},
                    },
                },
            },
        },
    },
}


class AITemplateContractsService:
    """Provides AI-facing template contracts backed by template_definitions.

    Each contract includes the JSON Schema, business rules, schema
    signature, and metadata needed by the AI agent to generate valid
    tool calls.
    """

    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    async def list_contracts(
        self, *, include_legacy: bool = False
    ) -> List[Dict[str, Any]]:
        """List all template contracts available to the AI agent.

        Reads from template_definitions table. Falls back to built-in
        schemas if no DB record exists for a type. If no DB session was
        provided, returns fallback schemas only.
        """
        seen_types: set = set()
        contracts: list = []

        # Query active template definitions if DB is available
        if self.db is not None:
            q = select(TemplateDefinitionRecord).order_by(
                TemplateDefinitionRecord.template_type
            )
            if not include_legacy:
                q = q.where(TemplateDefinitionRecord.is_active == True)  # noqa: E712

            result = await self.db.execute(q)
            records = list(result.scalars().all())

            for record in records:
                seen_types.add(record.template_type)
                contracts.append(self._record_to_contract(record))

        # Add fallback contracts for types not in DB
        for type_key, schema in _FALLBACK_SCHEMAS.items():
            if type_key not in seen_types:
                contracts.append(self._fallback_contract(type_key, schema))

        return contracts

    async def get_contract(
        self, type_key: str
    ) -> Optional[Dict[str, Any]]:
        """Get a single template contract by type key.

        Returns None if the type is unknown (not in DB and not in fallbacks).
        If no DB session was provided, checks fallback schemas only.
        """
        # Try DB first if available
        if self.db is not None:
            q = select(TemplateDefinitionRecord).where(
                TemplateDefinitionRecord.template_type == type_key
            )
            result = await self.db.execute(q)
            record = result.scalar_one_or_none()

            if record is not None:
                return self._record_to_contract(record)

        # Fall back to built-in schemas
        schema = _FALLBACK_SCHEMAS.get(type_key)
        if schema is not None:
            return self._fallback_contract(type_key, schema)

        return None

    async def get_schema_for_type(
        self, type_key: str
    ) -> Optional[Dict[str, Any]]:
        """Get just the JSON Schema for a template type.

        Returns None if the type is unknown.
        If no DB session was provided, checks fallback schemas only.
        """
        # Try DB first if available
        if self.db is not None:
            q = select(TemplateDefinitionRecord).where(
                TemplateDefinitionRecord.template_type == type_key
            )
            result = await self.db.execute(q)
            record = result.scalar_one_or_none()

            if record is not None:
                schema = record.schema_json
                if isinstance(schema, dict):
                    # Extract the JSON Schema portion — schema_json may
                    # contain render_config, field_schema, etc. wrapped
                    return self._extract_json_schema(type_key, schema)

        # Fall back
        return _FALLBACK_SCHEMAS.get(type_key)

    def _record_to_contract(
        self, record: TemplateDefinitionRecord
    ) -> Dict[str, Any]:
        """Convert a DB record to the AI contract format."""
        schema = record.schema_json
        if isinstance(schema, dict):
            json_schema = self._extract_json_schema(record.template_type, schema)
        else:
            json_schema = _FALLBACK_SCHEMAS.get(record.template_type, {})

        rules = BUSINESS_RULES.get(record.template_type, {})
        signature = record.schema_signature or ""
        if not signature and json_schema:
            signature = SchemaInferenceEngine.compute_schema_signature(
                json_schema
            )

        return {
            "type_key": record.template_type,
            "display_name": getattr(
                record, "display_name",
                record.template_type.replace("-", " ").title()
            ),
            "version": "1.0.0",
            "schema_signature": signature,
            "is_active": bool(record.is_active),
            "allowed": bool(record.is_active),
            "validation_rules": {
                "required_fields": rules.get("required_fields", []),
                "optional_fields": rules.get("optional_fields", []),
                "max_length": rules.get("max_length", {}),
                "constraints": rules.get("constraints", {}),
            },
        }

    def _fallback_contract(
        self, type_key: str, schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a contract from the built-in fallback schema."""
        signature = SchemaInferenceEngine.compute_schema_signature(schema)
        rules = BUSINESS_RULES.get(type_key, {})

        return {
            "type_key": type_key,
            "display_name": type_key.replace("-", " ").title(),
            "version": "1.0.0",
            "schema_signature": signature,
            "is_active": True,
            "allowed": True,
            "validation_rules": {
                "required_fields": rules.get("required_fields", []),
                "optional_fields": rules.get("optional_fields", []),
                "max_length": rules.get("max_length", {}),
                "constraints": rules.get("constraints", {}),
            },
        }

    def _extract_json_schema(
        self, type_key: str, schema_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract a clean JSON Schema from a schema_json payload.

        The schema_json in template_definitions may wrap the actual
        JSON Schema inside render_config, field_schema, etc. This
        method extracts or reconstructs the JSON Schema.
        """
        # If the payload already looks like a JSON Schema (has "type" key
        # at the top level), return it as-is.
        if "type" in schema_payload and "properties" in schema_payload:
            return schema_payload

        # If it has field_schema, reconstruct a JSON Schema from it
        fields = schema_payload.get("field_schema") or schema_payload.get("fields")
        if isinstance(fields, list) and fields:
            properties = {}
            required = []
            for f in fields:
                if not isinstance(f, dict):
                    continue
                name = f.get("name", "field")
                ftype = f.get("type", "string")
                json_type = self._map_field_type_to_json(ftype)
                properties[name] = {"type": json_type}
                if f.get("required", True):
                    required.append(name)

            return {
                "type": "object",
                "required": required,
                "properties": properties,
            }

        # Fall back to the built-in schema for this type
        return _FALLBACK_SCHEMAS.get(type_key, {})

    def _map_field_type_to_json(self, field_type: str) -> str:
        """Map internal field types to JSON Schema types."""
        mapping = {
            "text": "string",
            "html": "string",
            "richtext": "string",
            "string": "string",
            "number": "number",
            "integer": "integer",
            "boolean": "boolean",
            "list": "array",
            "array": "array",
            "object": "object",
        }
        return mapping.get(field_type, "string")
