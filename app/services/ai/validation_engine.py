"""AI Template Validation Engine.

Validates AI-proposed template data against JSON Schema definitions
and per-template-type business rules. Returns structured validation
results that the AI agent can use to correct errors.

Uses the jsonschema library (same as DynamicTemplateRenderer.validate())
for JSON Schema validation. Business rules are defined in
template_contracts.BUSINESS_RULES.

TODOs by story:
    US-BKND-AI-008: Integrate into propose_create/update_page flow.
    US-BKND-AI-035: Add WCAG accessibility checks as warnings.
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any, Literal

from pydantic import BaseModel, Field

from app.services.ai.template_contracts import (
    AITemplateContractsService,
    BUSINESS_RULES,
)

logger = logging.getLogger("ai_authoring")

# ═══════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════

class ValidationMessage(BaseModel):
    """A single validation finding — error, warning, or info."""

    severity: Literal["error", "warning", "info"] = "error"
    code: str = ""                  # e.g. "MISSING_REQUIRED_FIELD"
    field: str = ""                 # JSON path like "data.tabs[0].title"
    message: str = ""               # Human-readable description
    hint: Optional[str] = None      # Suggestion for how to fix
    min: Optional[int] = None       # For min constraints
    max: Optional[int] = None       # For max constraints
    actual: Optional[int] = None    # For boundary violations


class ValidationResult(BaseModel):
    """Result of validating template data against schema + business rules."""

    status: Literal["valid", "warning", "error"] = "valid"
    schema_status: Literal["valid", "error"] = "valid"
    business_rules_status: Literal["valid", "warning", "error"] = "valid"
    messages: List[ValidationMessage] = Field(default_factory=list)
    schema_signature: Optional[str] = None
    template_version: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# Validation Engine
# ═══════════════════════════════════════════════════════════════════

class TemplateValidationEngine:
    """Validates AI-proposed template data against schemas + business rules.

    Usage:
        engine = TemplateValidationEngine(contracts_service)
        result = await engine.validate("tabs", data)
        if result.status == "valid":
            # proceed with proposal creation
    """

    def __init__(self, contracts_service: AITemplateContractsService):
        self.contracts = contracts_service

    async def validate(
        self,
        template_type: str,
        data: Dict[str, Any],
        scope: Literal["schema_only", "business_rules", "full"] = "full",
    ) -> ValidationResult:
        """Validate template data.

        Args:
            template_type: One of the known template type keys.
            data: The proposed template data payload.
            scope: 'schema_only' (JSON Schema only), 'business_rules'
                   (business rules only), or 'full' (both).

        Returns:
            ValidationResult with status and any messages.
        """
        messages: List[ValidationMessage] = []
        schema_status: Literal["valid", "error"] = "valid"
        business_status: Literal["valid", "warning", "error"] = "valid"
        signature: Optional[str] = None
        version: Optional[str] = None

        # Get the contract (validates type_key exists)
        contract = await self.contracts.get_contract(template_type)
        if contract is None:
            return ValidationResult(
                status="error",
                schema_status="error",
                business_rules_status="error",
                messages=[
                    ValidationMessage(
                        severity="error",
                        code="TEMPLATE_TYPE_NOT_FOUND",
                        field="template_type",
                        message=(
                            f"Unknown template type: '{template_type}'. "
                            f"Supported types: {list(BUSINESS_RULES.keys())}"
                        ),
                    )
                ],
            )

        signature = contract.get("schema_signature")
        version = contract.get("version")

        # ── Schema Validation ──────────────────────────────
        if scope in ("schema_only", "full"):
            schema = await self.contracts.get_schema_for_type(template_type)
            if schema:
                schema_msgs = self._validate_schema(schema, data)
                messages.extend(schema_msgs)
                if any(m.severity == "error" for m in schema_msgs):
                    schema_status = "error"

        # ── Business Rule Validation ───────────────────────
        if scope in ("business_rules", "full"):
            rules = BUSINESS_RULES.get(template_type, {})
            if rules:
                business_msgs = self._validate_business_rules(
                    template_type, data, rules
                )
                messages.extend(business_msgs)
                if any(m.severity == "error" for m in business_msgs):
                    business_status = "error"
                elif any(m.severity == "warning" for m in business_msgs):
                    if business_status != "error":
                        business_status = "warning"

        # ── Determine overall status ───────────────────────
        if schema_status == "error" or business_status == "error":
            overall_status: Literal["valid", "warning", "error"] = "error"
        elif business_status == "warning":
            overall_status = "warning"
        else:
            overall_status = "valid"

        return ValidationResult(
            status=overall_status,
            schema_status=schema_status,
            business_rules_status=business_status,
            messages=messages,
            schema_signature=signature,
            template_version=version,
        )

    def _validate_schema(
        self, schema: Dict[str, Any], data: Dict[str, Any]
    ) -> List[ValidationMessage]:
        """Validate data against a JSON Schema using jsonschema library.

        Maps jsonschema error types to our error codes.
        """
        try:
            import jsonschema
            jsonschema.validate(instance=data, schema=schema)
            return []
        except ImportError:
            logger.warning(
                "jsonschema library not available — skipping schema validation"
            )
            return []
        except jsonschema.ValidationError as exc:
            return [self._map_jsonschema_error(exc)]
        except jsonschema.SchemaError as exc:
            logger.error("Invalid schema: %s", exc.message)
            return [
                ValidationMessage(
                    severity="error",
                    code="VALIDATION_ENGINE_ERROR",
                    field="",
                    message=f"Schema definition error: {exc.message}",
                )
            ]

    def _validate_business_rules(
        self,
        template_type: str,
        data: Dict[str, Any],
        rules: Dict[str, Any],
    ) -> List[ValidationMessage]:
        """Validate against per-template-type business rules.

        Checks:
        - Required fields are present
        - Array constraints (min_items, max_items)
        - Numeric constraints (min, max for scores)
        - String length constraints
        """
        messages: List[ValidationMessage] = []
        constraints = rules.get("constraints", {})
        required_fields = rules.get("required_fields", [])
        max_length = rules.get("max_length", {})

        # Required field checks
        for field in required_fields:
            if field not in data or data[field] is None:
                messages.append(
                    ValidationMessage(
                        severity="error",
                        code="MISSING_REQUIRED_FIELD",
                        field=f"data.{field}",
                        message=(
                            f"Required field '{field}' is missing "
                            f"for template type '{template_type}'."
                        ),
                        hint=f"Add the '{field}' field to your data payload.",
                    )
                )

        # Only check constraints for fields that exist
        for field, constraint in constraints.items():
            if field not in data or data[field] is None:
                continue

            value = data[field]

            # Array item count constraints
            if isinstance(value, list):
                min_items = constraint.get("min_items")
                max_items = constraint.get("max_items")
                actual = len(value)

                if min_items is not None and actual < min_items:
                    messages.append(
                        ValidationMessage(
                            severity="error",
                            code="MIN_ITEMS_VIOLATION",
                            field=f"data.{field}",
                            message=(
                                f"Field '{field}' must have at least "
                                f"{min_items} items, got {actual}."
                            ),
                            hint=f"Add at least {min_items - actual} more "
                                 f"item(s) or use a different template type.",
                            min=min_items,
                            actual=actual,
                        )
                    )

                if max_items is not None and actual > max_items:
                    messages.append(
                        ValidationMessage(
                            severity="error",
                            code="MAX_ITEMS_VIOLATION",
                            field=f"data.{field}",
                            message=(
                                f"Field '{field}' must have at most "
                                f"{max_items} items, got {actual}."
                            ),
                            hint=f"Reduce to {max_items} or fewer items.",
                            max=max_items,
                            actual=actual,
                        )
                    )

            # Numeric constraints
            if isinstance(value, (int, float)):
                cmin = constraint.get("min")
                cmax = constraint.get("max")

                if cmin is not None and value < cmin:
                    messages.append(
                        ValidationMessage(
                            severity="error",
                            code="BUSINESS_RULE_VIOLATION",
                            field=f"data.{field}",
                            message=(
                                f"Field '{field}' must be >= {cmin}, "
                                f"got {value}."
                            ),
                            min=cmin,
                            actual=value,
                        )
                    )

                if cmax is not None and value > cmax:
                    messages.append(
                        ValidationMessage(
                            severity="error",
                            code="BUSINESS_RULE_VIOLATION",
                            field=f"data.{field}",
                            message=(
                                f"Field '{field}' must be <= {cmax}, "
                                f"got {value}."
                            ),
                            max=cmax,
                            actual=value,
                        )
                    )

        # String length checks
        for field, max_len in max_length.items():
            # Handle nested paths like "tabs[].title"
            if "[]" in field:
                continue  # Skip nested for now — schema validation catches these

            if field in data and isinstance(data[field], str):
                actual_len = len(data[field])
                if actual_len > max_len:
                    messages.append(
                        ValidationMessage(
                            severity="error",
                            code="MAX_LENGTH_VIOLATION",
                            field=f"data.{field}",
                            message=(
                                f"Field '{field}' must be at most "
                                f"{max_len} characters, got {actual_len}."
                            ),
                            max=max_len,
                            actual=actual_len,
                        )
                    )

        return messages

    def _map_jsonschema_error(
        self, exc
    ) -> ValidationMessage:
        """Map a jsonschema.ValidationError to our ValidationMessage format."""
        import jsonschema

        # Build JSON path from the error's path
        path = "data"
        if exc.absolute_path:
            path_parts = []
            for p in exc.absolute_path:
                if isinstance(p, int):
                    if path_parts:
                        path_parts[-1] = f"{path_parts[-1]}[{p}]"
                    else:
                        path_parts.append(f"[{p}]")
                else:
                    path_parts.append(str(p))
            path = "data." + ".".join(path_parts) if path_parts else "data"

        message = exc.message
        hint = None

        # Map validator types to error codes
        validator_to_code = {
            "required": "MISSING_REQUIRED_FIELD",
            "type": "INVALID_TYPE",
            "minItems": "MIN_ITEMS_VIOLATION",
            "maxItems": "MAX_ITEMS_VIOLATION",
            "minLength": "MIN_LENGTH_VIOLATION",
            "maxLength": "MAX_LENGTH_VIOLATION",
            "minimum": "BUSINESS_RULE_VIOLATION",
            "maximum": "BUSINESS_RULE_VIOLATION",
            "enum": "INVALID_ENUM_VALUE",
            "additionalProperties": "BUSINESS_RULE_VIOLATION",
        }
        code = validator_to_code.get(exc.validator, "BUSINESS_RULE_VIOLATION")

        # Provide helpful hints
        if exc.validator == "required":
            missing = exc.message.split("'")[1] if "'" in exc.message else "field"
            hint = f"Add the '{missing}' field to your data payload."

        # Build the message
        return ValidationMessage(
            severity="error",
            code=code,
            field=path,
            message=message,
            hint=hint,
            **self._extract_boundary_info(exc),
        )

    def _extract_boundary_info(self, exc) -> Dict[str, Any]:
        """Extract min/max/actual values from a jsonschema error."""
        info = {}
        try:
            if hasattr(exc, "validator_value"):
                if exc.validator in ("minItems", "minLength", "minimum"):
                    info["min"] = exc.validator_value
                elif exc.validator in ("maxItems", "maxLength", "maximum"):
                    info["max"] = exc.validator_value
        except Exception:
            pass
        return info
