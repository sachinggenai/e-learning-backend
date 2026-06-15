"""
Tests for US-BKND-AI-005 — Version Tool Schemas and Template Contracts.

Covers:
    - Business rules for all 5 template types
    - Validation engine (schema + business rules)
    - Template contracts service
    - Templates router endpoints
    - Validate endpoint wiring
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ═══════════════════════════════════════════════════════════════════
# Business Rules Tests
# ═══════════════════════════════════════════════════════════════════

class TestBusinessRules:
    """Verify business rule definitions for all 5 template types."""

    def test_all_five_types_defined(self):
        from app.services.ai.template_contracts import BUSINESS_RULES
        assert "text-content" in BUSINESS_RULES
        assert "tabs" in BUSINESS_RULES
        assert "accordion" in BUSINESS_RULES
        assert "click-reveal" in BUSINESS_RULES
        assert "final-assessment" in BUSINESS_RULES
        assert len(BUSINESS_RULES) == 5

    def test_text_content_rules(self):
        from app.services.ai.template_contracts import BUSINESS_RULES
        rules = BUSINESS_RULES["text-content"]
        assert "title" in rules["required_fields"]
        assert "content" in rules["required_fields"]
        assert rules["max_length"]["title"] == 200

    def test_tabs_rules(self):
        from app.services.ai.template_contracts import BUSINESS_RULES
        rules = BUSINESS_RULES["tabs"]
        assert "title" in rules["required_fields"]
        assert "tabs" in rules["required_fields"]
        tabs_c = rules["constraints"]["tabs"]
        assert tabs_c["min_items"] == 2
        assert tabs_c["max_items"] == 6

    def test_accordion_rules(self):
        from app.services.ai.template_contracts import BUSINESS_RULES
        rules = BUSINESS_RULES["accordion"]
        items_c = rules["constraints"]["items"]
        assert items_c["min_items"] == 2
        assert items_c["max_items"] == 20

    def test_click_reveal_rules(self):
        from app.services.ai.template_contracts import BUSINESS_RULES
        rules = BUSINESS_RULES["click-reveal"]
        items_c = rules["constraints"]["items"]
        assert items_c["min_items"] == 2
        assert items_c["max_items"] == 10

    def test_final_assessment_rules(self):
        from app.services.ai.template_contracts import BUSINESS_RULES
        rules = BUSINESS_RULES["final-assessment"]
        assert "passing_score" in rules["required_fields"]
        assert "questions" in rules["required_fields"]
        ps_c = rules["constraints"]["passing_score"]
        assert ps_c["min"] == 0
        assert ps_c["max"] == 100
        qs_c = rules["constraints"]["questions"]
        assert qs_c["min_items"] == 3
        assert qs_c["max_items"] == 50


# ═══════════════════════════════════════════════════════════════════
# Validation Engine Tests
# ═══════════════════════════════════════════════════════════════════

class TestValidationEngine:
    """Unit tests for TemplateValidationEngine."""

    @pytest.mark.asyncio
    async def test_validate_valid_tabs_data(self):
        """Valid tabs payload passes validation."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        # Mock the contracts service
        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = {
            "type_key": "tabs",
            "schema_signature": "abc123",
            "version": "1.0.0",
        }
        mock_contracts.get_schema_for_type.return_value = {
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
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                },
            },
        }

        engine = TemplateValidationEngine(mock_contracts)

        valid_data = {
            "title": "Cloud Comparison",
            "tabs": [
                {"title": "AWS", "content": "Amazon Web Services"},
                {"title": "Azure", "content": "Microsoft Azure"},
            ],
        }

        # Without jsonschema installed, schema validation returns [] (graceful)
        result = await engine.validate("tabs", valid_data)

        assert result.status in ("valid", "warning")
        assert result.schema_signature == "abc123"

    @pytest.mark.asyncio
    async def test_validate_missing_required_field(self):
        """Data missing a required field returns error."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = {
            "type_key": "text-content",
            "schema_signature": "def456",
            "version": "1.0.0",
        }
        mock_contracts.get_schema_for_type.return_value = {
            "type": "object",
            "required": ["title", "content"],
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
        }

        engine = TemplateValidationEngine(mock_contracts)

        # Missing 'content'
        data = {"title": "Intro"}
        result = await engine.validate("text-content", data)

        # Business rules catch the missing required field
        assert result.status == "error"
        assert result.business_rules_status == "error"
        assert any(
            m.code == "MISSING_REQUIRED_FIELD" and m.field == "data.content"
            for m in result.messages
        )

    @pytest.mark.asyncio
    async def test_validate_tabs_too_few_items(self):
        """Tabs with only 1 item fails min_items constraint."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = {
            "type_key": "tabs",
            "schema_signature": "abc",
            "version": "1.0.0",
        }
        mock_contracts.get_schema_for_type.return_value = {
            "type": "object",
            "properties": {"title": {"type": "string"}, "tabs": {"type": "array"}},
        }

        engine = TemplateValidationEngine(mock_contracts)

        data = {
            "title": "Single Tab",
            "tabs": [{"title": "Only", "content": "One tab"}],
        }
        result = await engine.validate("tabs", data)

        assert result.status == "error"
        assert any(
            m.code == "MIN_ITEMS_VIOLATION" and m.field == "data.tabs"
            for m in result.messages
        )

    @pytest.mark.asyncio
    async def test_validate_tabs_too_many_items(self):
        """Tabs with 7 items fails max_items constraint."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = {
            "type_key": "tabs",
            "schema_signature": "abc",
            "version": "1.0.0",
        }
        mock_contracts.get_schema_for_type.return_value = {
            "type": "object",
            "properties": {"title": {"type": "string"}, "tabs": {"type": "array"}},
        }

        engine = TemplateValidationEngine(mock_contracts)

        data = {
            "title": "Too Many",
            "tabs": [
                {"title": f"Tab {i}", "content": f"Content {i}"}
                for i in range(7)
            ],
        }
        result = await engine.validate("tabs", data)

        assert result.status == "error"
        assert any(
            m.code == "MAX_ITEMS_VIOLATION" and m.field == "data.tabs"
            for m in result.messages
        )

    @pytest.mark.asyncio
    async def test_validate_passing_score_out_of_range(self):
        """Passing score > 100 fails business rule."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = {
            "type_key": "final-assessment",
            "schema_signature": "ghi789",
            "version": "1.0.0",
        }
        mock_contracts.get_schema_for_type.return_value = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "passing_score": {"type": "integer"},
                "questions": {"type": "array"},
            },
        }

        engine = TemplateValidationEngine(mock_contracts)

        data = {
            "title": "Quiz",
            "passing_score": 150,
            "questions": [
                {"question": "Q1", "options": [{"id": "a", "text": "A", "isCorrect": True}], "correctAnswer": "a"},
                {"question": "Q2", "options": [{"id": "a", "text": "A", "isCorrect": True}], "correctAnswer": "a"},
                {"question": "Q3", "options": [{"id": "a", "text": "A", "isCorrect": True}], "correctAnswer": "a"},
            ],
        }
        result = await engine.validate("final-assessment", data)

        assert result.status == "error"
        assert any(
            m.code == "BUSINESS_RULE_VIOLATION" and m.field == "data.passing_score"
            for m in result.messages
        )

    @pytest.mark.asyncio
    async def test_validate_assessment_too_few_questions(self):
        """Assessment with only 2 questions fails."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = {
            "type_key": "final-assessment",
            "schema_signature": "jkl",
            "version": "1.0.0",
        }
        mock_contracts.get_schema_for_type.return_value = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "passing_score": {"type": "integer"},
                "questions": {"type": "array"},
            },
        }

        engine = TemplateValidationEngine(mock_contracts)

        data = {
            "title": "Short Quiz",
            "passing_score": 70,
            "questions": [
                {"question": "Q1", "options": [], "correctAnswer": "a"},
                {"question": "Q2", "options": [], "correctAnswer": "b"},
            ],
        }
        result = await engine.validate("final-assessment", data)

        assert result.status == "error"
        assert any(
            m.code == "MIN_ITEMS_VIOLATION" and m.field == "data.questions"
            for m in result.messages
        )

    @pytest.mark.asyncio
    async def test_validate_unknown_template_type(self):
        """Unknown template type returns TEMPLATE_TYPE_NOT_FOUND."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = None  # Not found

        engine = TemplateValidationEngine(mock_contracts)

        result = await engine.validate("nonexistent-type", {})
        assert result.status == "error"
        assert result.schema_status == "error"
        assert any(
            m.code == "TEMPLATE_TYPE_NOT_FOUND"
            for m in result.messages
        )

    @pytest.mark.asyncio
    async def test_validate_schema_only_scope(self):
        """schema_only scope skips business rules."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = {
            "type_key": "tabs",
            "schema_signature": "abc",
            "version": "1.0.0",
        }
        mock_contracts.get_schema_for_type.return_value = {
            "type": "object",
            "properties": {"title": {"type": "string"}, "tabs": {"type": "array"}},
        }

        engine = TemplateValidationEngine(mock_contracts)

        # Only 1 tab (would fail business rules) but schema_only skips them
        data = {
            "title": "Single Tab",
            "tabs": [{"title": "Only", "content": "One tab"}],
        }
        result = await engine.validate("tabs", data, scope="schema_only")

        # Business rules are skipped, so status should be valid
        assert result.business_rules_status == "valid"

    @pytest.mark.asyncio
    async def test_validate_accordion_boundary(self):
        """Accordion with exactly 2 items (boundary) passes."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from app.services.ai.validation_engine import TemplateValidationEngine

        mock_contracts = AsyncMock(spec=AITemplateContractsService)
        mock_contracts.get_contract.return_value = {
            "type_key": "accordion",
            "schema_signature": "acc",
            "version": "1.0.0",
        }
        mock_contracts.get_schema_for_type.return_value = {
            "type": "object",
            "properties": {"title": {"type": "string"}, "items": {"type": "array"}},
        }

        engine = TemplateValidationEngine(mock_contracts)

        data = {
            "title": "FAQ",
            "items": [
                {"title": "Q1", "content": "Answer 1"},
                {"title": "Q2", "content": "Answer 2"},
            ],
        }
        result = await engine.validate("accordion", data)

        # Should not have MIN_ITEMS or MAX_ITEMS violations
        assert not any(
            m.code in ("MIN_ITEMS_VIOLATION", "MAX_ITEMS_VIOLATION")
            for m in result.messages
        )


# ═══════════════════════════════════════════════════════════════════
# Validation Message Model Tests
# ═══════════════════════════════════════════════════════════════════

class TestValidationModels:
    """Tests for ValidationResult and ValidationMessage Pydantic models."""

    def test_validation_message_creation(self):
        from app.services.ai.validation_engine import ValidationMessage
        msg = ValidationMessage(
            severity="error",
            code="MIN_ITEMS_VIOLATION",
            field="data.tabs",
            message="Must have at least 2 items, got 1",
            hint="Add another tab",
            min=2,
            actual=1,
        )
        assert msg.severity == "error"
        assert msg.code == "MIN_ITEMS_VIOLATION"
        assert msg.min == 2
        assert msg.actual == 1

    def test_validation_result_defaults(self):
        from app.services.ai.validation_engine import ValidationResult
        result = ValidationResult()
        assert result.status == "valid"
        assert result.schema_status == "valid"
        assert result.business_rules_status == "valid"
        assert result.messages == []
        assert result.schema_signature is None

    def test_validation_result_with_errors(self):
        from app.services.ai.validation_engine import (
            ValidationResult, ValidationMessage
        )
        result = ValidationResult(
            status="error",
            schema_status="error",
            messages=[
                ValidationMessage(
                    severity="error",
                    code="MISSING_REQUIRED_FIELD",
                    field="data.title",
                    message="Required field missing",
                ),
            ],
        )
        assert result.status == "error"
        assert len(result.messages) == 1


# ═══════════════════════════════════════════════════════════════════
# Template Contracts Service Tests
# ═══════════════════════════════════════════════════════════════════

class TestTemplateContractsService:
    """Tests for AITemplateContractsService."""

    def test_service_importable(self):
        from app.services.ai.template_contracts import AITemplateContractsService
        assert callable(AITemplateContractsService)

    def test_fallback_schemas_available(self):
        from app.services.ai.template_contracts import _FALLBACK_SCHEMAS
        assert "text-content" in _FALLBACK_SCHEMAS
        assert "tabs" in _FALLBACK_SCHEMAS
        assert "accordion" in _FALLBACK_SCHEMAS
        assert "click-reveal" in _FALLBACK_SCHEMAS
        assert "final-assessment" in _FALLBACK_SCHEMAS

        # Each fallback schema should have type and properties
        for key, schema in _FALLBACK_SCHEMAS.items():
            assert "type" in schema, f"{key} missing 'type'"
            assert schema["type"] == "object", f"{key} type is {schema['type']}"
            assert "properties" in schema, f"{key} missing 'properties'"

    def test_map_field_type_to_json(self):
        from app.services.ai.template_contracts import AITemplateContractsService
        from unittest.mock import MagicMock

        svc = AITemplateContractsService(MagicMock())
        assert svc._map_field_type_to_json("text") == "string"
        assert svc._map_field_type_to_json("html") == "string"
        assert svc._map_field_type_to_json("number") == "number"
        assert svc._map_field_type_to_json("boolean") == "boolean"
        assert svc._map_field_type_to_json("list") == "array"
        assert svc._map_field_type_to_json("unknown") == "string"

    def test_extract_json_schema_from_field_schema(self):
        from app.services.ai.template_contracts import AITemplateContractsService
        from unittest.mock import MagicMock

        svc = AITemplateContractsService(MagicMock())

        payload = {
            "field_schema": [
                {"name": "title", "type": "text", "required": True},
                {"name": "content", "type": "html", "required": True},
                {"name": "subtitle", "type": "text", "required": False},
            ],
        }

        result = svc._extract_json_schema("text-content", payload)
        assert result["type"] == "object"
        assert "title" in result["required"]
        assert "content" in result["required"]
        assert "subtitle" in result["properties"]

    def test_minimal_contract_has_required_fields(self):
        """Every contract (including fallback) has required shape."""
        from app.services.ai.template_contracts import AITemplateContractsService
        from unittest.mock import MagicMock

        svc = AITemplateContractsService(MagicMock())
        contract = svc._fallback_contract(
            "tabs",
            {
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
        )
        assert contract["type_key"] == "tabs"
        assert contract["is_active"] is True
        assert contract["allowed"] is True
        assert "schema_signature" in contract
        assert len(contract["schema_signature"]) == 64  # SHA-256 hex


# ═══════════════════════════════════════════════════════════════════
# Router Tests
# ═══════════════════════════════════════════════════════════════════

class TestTemplatesRouter:
    """Tests for ai_templates router structure."""

    def test_router_has_correct_prefix(self):
        from app.routers.ai_templates import router
        assert router.prefix == "/api/v1/ai"

    def test_router_has_list_endpoint(self):
        from app.routers.ai_templates import router
        paths = {r.path: r.methods for r in router.routes}
        assert "/api/v1/ai/templates" in paths
        assert "GET" in paths["/api/v1/ai/templates"]

    def test_router_has_detail_endpoint(self):
        from app.routers.ai_templates import router
        paths = {r.path: r.methods for r in router.routes}
        assert "/api/v1/ai/templates/{type_key}" in paths
        assert "GET" in paths["/api/v1/ai/templates/{type_key}"]


class TestValidateEndpoint:
    """Tests for the POST /tools/validate endpoint."""

    def test_validate_endpoint_exists(self):
        from app.routers.ai_tools import router
        paths = {r.path: r.methods for r in router.routes}
        assert "/api/v1/ai/tools/validate" in paths
        assert "POST" in paths["/api/v1/ai/tools/validate"]

    def test_validate_request_model(self):
        from app.routers.ai_tools import ValidateRequest
        req = ValidateRequest(
            session_id="sess-001",
            template_type="tabs",
            data={"title": "Test", "tabs": []},
        )
        assert req.session_id == "sess-001"
        assert req.template_type == "tabs"
        assert req.validation_scope == "full"  # default

    def test_validate_request_custom_scope(self):
        from app.routers.ai_tools import ValidateRequest
        req = ValidateRequest(
            session_id="sess-001",
            template_type="tabs",
            data={},
            validation_scope="schema_only",
        )
        assert req.validation_scope == "schema_only"


# ═══════════════════════════════════════════════════════════════════
# Signature Computation Test
# ═══════════════════════════════════════════════════════════════════

class TestSchemaSignature:
    """Verify schema signature computation is deterministic."""

    def test_signature_is_64_char_hex(self):
        from app.services.schema_inference import SchemaInferenceEngine

        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        sig = SchemaInferenceEngine.compute_schema_signature(schema)
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_signature_deterministic(self):
        from app.services.schema_inference import SchemaInferenceEngine

        schema = {
            "type": "object",
            "properties": {
                "b": {"type": "integer"},
                "a": {"type": "string"},
            },
        }
        sig1 = SchemaInferenceEngine.compute_schema_signature(schema)
        sig2 = SchemaInferenceEngine.compute_schema_signature(schema)
        assert sig1 == sig2

    def test_signature_changes_with_schema(self):
        from app.services.schema_inference import SchemaInferenceEngine

        s1 = {"type": "object", "properties": {"a": {"type": "string"}}}
        s2 = {"type": "object", "properties": {"a": {"type": "integer"}}}
        assert (
            SchemaInferenceEngine.compute_schema_signature(s1)
            != SchemaInferenceEngine.compute_schema_signature(s2)
        )
