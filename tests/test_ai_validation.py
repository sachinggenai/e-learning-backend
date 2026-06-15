"""
Tests for US-BKND-AI-008 — Unified Validation Pipeline.

Covers:
    - CourseLevelValidator: structural + accessibility checks
    - UnifiedValidator: full-course validation orchestration
    - Router: POST /tools/validate_course endpoint
    - ValidationScope enum
    - Categorized output (errors, warnings, info)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════
# CourseLevelValidator — Structural Checks
# ═══════════════════════════════════════════════════════════════════

class TestCourseLevelValidatorStructural:
    """FR-004: Course-level structural validation."""

    @pytest.fixture
    def validator(self):
        from app.services.validation.course_validator import CourseLevelValidator
        return CourseLevelValidator()

    def test_empty_course_error(self, validator):
        """Empty course produces COURSE_EMPTY error."""
        issues = validator.validate_course_structure([])
        assert len(issues) == 1
        assert issues[0].code == "COURSE_EMPTY"
        assert issues[0].severity == "error"

    def test_valid_course_no_issues(self, validator):
        """Well-formed course produces no issues."""
        pages = [
            {"page_id": "p1", "title": "Page 1", "order": 0,
             "template_type": "text-content", "components": [{"component_id": "c1"}]},
            {"page_id": "p2", "title": "Page 2", "order": 1,
             "template_type": "tabs", "components": [{"component_id": "c2"}]},
        ]
        issues = validator.validate_course_structure(pages)
        assert len(issues) == 0

    def test_page_order_gap(self, validator):
        """Missing order index produces PAGE_ORDER_GAP error."""
        pages = [
            {"page_id": "p1", "title": "P1", "order": 0,
             "template_type": "text-content", "components": [{"component_id": "c1"}]},
            {"page_id": "p2", "title": "P2", "order": 2,  # Gap — missing 1
             "template_type": "text-content", "components": [{"component_id": "c2"}]},
        ]
        issues = validator.validate_course_structure(pages)
        assert any(i.code == "PAGE_ORDER_GAP" for i in issues)

    def test_duplicate_page_ids(self, validator):
        """Duplicate page IDs produce DUPLICATE_PAGE_ID error."""
        pages = [
            {"page_id": "dup-id", "title": "P1", "order": 0,
             "template_type": "text-content", "components": [{"component_id": "c1"}]},
            {"page_id": "dup-id", "title": "P2", "order": 1,
             "template_type": "text-content", "components": [{"component_id": "c2"}]},
        ]
        issues = validator.validate_course_structure(pages)
        assert any(i.code == "DUPLICATE_PAGE_ID" for i in issues)

    def test_unsupported_template_type(self, validator):
        """Unknown template type produces UNSUPPORTED_TEMPLATE_TYPE error."""
        pages = [
            {"page_id": "p1", "title": "P1", "order": 0,
             "template_type": "unknown-template-type",
             "components": [{"component_id": "c1"}]},
        ]
        issues = validator.validate_course_structure(pages)
        assert any(i.code == "UNSUPPORTED_TEMPLATE_TYPE" for i in issues)

    def test_page_no_components(self, validator):
        """Page with zero components produces PAGE_NO_COMPONENTS error."""
        pages = [
            {"page_id": "p1", "title": "Empty Page", "order": 0,
             "template_type": "text-content", "components": []},
        ]
        issues = validator.validate_course_structure(pages)
        assert any(i.code == "PAGE_NO_COMPONENTS" for i in issues)

    def test_contiguous_zero_based_orders_pass(self, validator):
        """Zero-based contiguous orders pass validation."""
        pages = [
            {"page_id": "p1", "title": "A", "order": 0,
             "template_type": "text-content", "components": [{"c": 1}]},
            {"page_id": "p2", "title": "B", "order": 1,
             "template_type": "text-content", "components": [{"c": 1}]},
            {"page_id": "p3", "title": "C", "order": 2,
             "template_type": "text-content", "components": [{"c": 1}]},
        ]
        assert validator.validate_course_structure(pages) == []

    def test_order_index_field_alias(self, validator):
        """order_index field is treated as alias for order."""
        pages = [
            {"page_id": "p1", "title": "A", "order_index": 0,
             "template_type": "text-content", "components": [{"c": 1}]},
            {"page_id": "p2", "title": "B", "order_index": 1,
             "template_type": "text-content", "components": [{"c": 1}]},
        ]
        issues = validator.validate_course_structure(pages)
        assert len(issues) == 0


# ═══════════════════════════════════════════════════════════════════
# CourseLevelValidator — Accessibility Checks
# ═══════════════════════════════════════════════════════════════════

class TestCourseLevelValidatorAccessibility:
    """FR-006: Accessibility heuristic checks."""

    @pytest.fixture
    def validator(self):
        from app.services.validation.course_validator import CourseLevelValidator
        return CourseLevelValidator()

    def test_page_title_too_short(self, validator):
        """Short page title produces PAGE_TITLE_TOO_SHORT warning."""
        pages = [
            {"page_id": "p1", "title": "AB", "order": 0, "template_type": "text-content",
             "components": [{"component_type": "text-content", "data": {"content": "X"}}]},
        ]
        issues = validator.validate_accessibility(pages)
        assert any(i.code == "PAGE_TITLE_TOO_SHORT" for i in issues)
        title_issue = [i for i in issues if i.code == "PAGE_TITLE_TOO_SHORT"][0]
        assert title_issue.severity == "warning"

    def test_page_title_valid(self, validator):
        """Descriptive page title produces no warning."""
        pages = [
            {"page_id": "p1", "title": "Introduction to AI", "order": 0,
             "template_type": "text-content",
             "components": [{"component_type": "text-content", "data": {"content": "X"}}]},
        ]
        issues = validator.validate_accessibility(pages)
        assert not any(i.code == "PAGE_TITLE_TOO_SHORT" for i in issues)

    def test_missing_alt_text_on_image(self, validator):
        """Image component without altText produces MISSING_ALT_TEXT warning."""
        pages = [
            {"page_id": "p1", "title": "Image Page", "order": 0,
             "template_type": "text-content",
             "components": [
                 {"component_type": "image", "data": {"src": "img.png"}}
             ]},
        ]
        issues = validator.validate_accessibility(pages)
        assert any(i.code == "MISSING_ALT_TEXT" for i in issues)
        alt_issue = [i for i in issues if i.code == "MISSING_ALT_TEXT"][0]
        assert alt_issue.severity == "warning"

    def test_image_with_alt_text_passes(self, validator):
        """Image with altText produces no warning."""
        pages = [
            {"page_id": "p1", "title": "Good Page", "order": 0,
             "template_type": "text-content",
             "components": [
                 {"component_type": "image", "data": {"src": "img.png", "altText": "A chart"}}
             ]},
        ]
        issues = validator.validate_accessibility(pages)
        assert not any(i.code == "MISSING_ALT_TEXT" for i in issues)

    def test_assessment_missing_instructions(self, validator):
        """Final-assessment without introText produces ASSESSMENT_MISSING_INSTRUCTIONS warning."""
        pages = [
            {"page_id": "p1", "title": "Quiz", "order": 0,
             "template_type": "final-assessment", "data": {},
             "components": [
                 {"component_type": "final-assessment",
                  "data": {"questions": [{"q": "Q1"}]}}
             ]},
        ]
        issues = validator.validate_accessibility(pages)
        assert any(i.code == "ASSESSMENT_MISSING_INSTRUCTIONS" for i in issues)

    def test_assessment_with_intro_passes(self, validator):
        """Final-assessment with introText produces no warning."""
        pages = [
            {"page_id": "p1", "title": "Quiz", "order": 0,
             "template_type": "final-assessment",
             "data": {"introText": "Please complete this quiz."},
             "components": [{"component_type": "final-assessment", "data": {}}]},
        ]
        issues = validator.validate_accessibility(pages)
        assert not any(i.code == "ASSESSMENT_MISSING_INSTRUCTIONS" for i in issues)

    def test_accessibility_always_warnings(self, validator):
        """All accessibility issues are warnings, not errors (FR-006)."""
        pages = [
            {"page_id": "p1", "title": "A", "order": 0,
             "template_type": "text-content",
             "components": [
                 {"component_type": "image", "data": {}}
             ]},
        ]
        issues = validator.validate_accessibility(pages)
        for issue in issues:
            assert issue.severity == "warning", f"{issue.code} should be warning"


# ═══════════════════════════════════════════════════════════════════
# UnifiedValidator Tests
# ═══════════════════════════════════════════════════════════════════

class TestUnifiedValidator:
    """Tests for UnifiedValidator orchestrator."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    def _make_page(self, page_id, title, order, ttype="text-content",
                   components=None):
        from app.models.page_component import PageRecord
        page = MagicMock()
        page.page_id = page_id
        page.title = title
        page.order_index = order
        page.layout = {"templateType": ttype}
        page.components = components or []
        return page

    def test_validate_course_empty(self, mock_db):
        """Empty course returns COURSE_EMPTY error."""
        import asyncio
        async def _test():
            from app.services.validation.unified_validator import (
                UnifiedValidator, ValidationScope
            )
            validator = UnifiedValidator(mock_db)
            with patch.object(validator.page_repo, "list_by_course", AsyncMock(
                return_value=[]
            )):
                result = await validator.validate_course("course-001", ValidationScope.FULL)

            assert result.is_valid is False
            assert any(e.code == "COURSE_EMPTY" for e in result.errors)
            assert result.metadata["pages_checked"] == 0

        asyncio.get_event_loop().run_until_complete(_test())

    def test_validate_course_valid(self, mock_db):
        """Valid course passes all checks."""
        import asyncio
        async def _test():
            from app.services.validation.unified_validator import (
                UnifiedValidator, ValidationScope
            )
            validator = UnifiedValidator(mock_db)

            page = self._make_page("p1", "Valid Page", 0, "text-content",
                                   components=[MagicMock()])
            page.components[0].component_id = "c1"
            page.components[0].component_type = "text-content"
            page.components[0].order_index = 0
            page.components[0].data = {"content": "Hello world"}

            with patch.object(validator.page_repo, "list_by_course", AsyncMock(
                return_value=[page]
            )):
                with patch.object(validator.template_engine, "validate", AsyncMock(
                    return_value=MagicMock(
                        status="valid", messages=[],
                        schema_status="valid", business_rules_status="valid",
                        schema_signature=None, template_version=None,
                    )
                )):
                    result = await validator.validate_course("course-001", ValidationScope.FULL)

            assert result.is_valid is True
            assert len(result.errors) == 0
            assert result.metadata["pages_checked"] == 1

        asyncio.get_event_loop().run_until_complete(_test())

    def test_validate_course_with_errors(self, mock_db):
        """Course with structural issues and validation errors returns errors."""
        import asyncio
        async def _test():
            from app.services.validation.unified_validator import (
                UnifiedValidator, ValidationScope
            )
            validator = UnifiedValidator(mock_db)

            page = self._make_page("p1", "Bad Page", 0, "tabs",
                                   components=[MagicMock()])
            page.components[0].component_id = "c1"
            page.components[0].component_type = "tabs"
            page.components[0].order_index = 0
            page.components[0].data = {"tabs": [{"title": "Only one"}]}

            mock_result = MagicMock()
            mock_result.status = "error"
            mock_result.messages = [MagicMock(
                severity="error", code="MIN_ITEMS_VIOLATION",
                field="data.tabs",
                message="Field 'tabs' must have at least 2 items, got 1.",
                hint="Add at least 1 more tab.",
            )]

            with patch.object(validator.page_repo, "list_by_course", AsyncMock(
                return_value=[page]
            )):
                with patch.object(validator.template_engine, "validate", AsyncMock(
                    return_value=mock_result
                )):
                    result = await validator.validate_course("course-001", ValidationScope.FULL)

            assert result.is_valid is False
            assert any(e.code == "MIN_ITEMS_VIOLATION" for e in result.errors)

        asyncio.get_event_loop().run_until_complete(_test())

    def test_validate_course_accessibility_warnings(self, mock_db):
        """Accessibility issues are returned as warnings."""
        import asyncio
        async def _test():
            from app.services.validation.unified_validator import (
                UnifiedValidator, ValidationScope
            )
            validator = UnifiedValidator(mock_db)

            page = self._make_page("p1", "AB", 0, "text-content",
                                   components=[MagicMock()])
            page.components[0].component_id = "c1"
            page.components[0].component_type = "image"
            page.components[0].order_index = 0
            page.components[0].data = {"src": "img.png"}  # No altText

            with patch.object(validator.page_repo, "list_by_course", AsyncMock(
                return_value=[page]
            )):
                with patch.object(validator.template_engine, "validate", AsyncMock(
                    return_value=MagicMock(
                        status="valid", messages=[], schema_status="valid",
                        business_rules_status="valid",
                        schema_signature=None, template_version=None,
                    )
                )):
                    result = await validator.validate_course("course-001", ValidationScope.FULL)

            # Has warnings for short title and missing alt text
            assert any(w.code == "PAGE_TITLE_TOO_SHORT" for w in result.warnings)
            assert any(w.code == "MISSING_ALT_TEXT" for w in result.warnings)
            # But no blocking errors
            assert result.is_valid is True

        asyncio.get_event_loop().run_until_complete(_test())

    def test_scope_schema_only(self, mock_db):
        """schema_only scope skips business rules and accessibility."""
        import asyncio
        async def _test():
            from app.services.validation.unified_validator import (
                UnifiedValidator, ValidationScope
            )
            validator = UnifiedValidator(mock_db)

            page = self._make_page("p1", "Good Page Title", 0, "text-content",
                                   components=[MagicMock()])
            page.components[0].component_id = "c1"
            page.components[0].component_type = "text-content"
            page.components[0].order_index = 0
            page.components[0].data = {"content": "Hello"}

            with patch.object(validator.page_repo, "list_by_course", AsyncMock(
                return_value=[page]
            )):
                with patch.object(validator.template_engine, "validate", AsyncMock(
                    return_value=MagicMock(
                        status="valid", messages=[], schema_status="valid",
                        business_rules_status="valid",
                        schema_signature=None, template_version=None,
                    )
                )) as mock_validate:
                    result = await validator.validate_course(
                        "course-001", ValidationScope.SCHEMA_ONLY
                    )

            # Schema-only should not run accessibility checks
            # (no accessibility warnings should be present)
            assert result.is_valid is True
            # The engine should be called with schema_only
            call_scope = mock_validate.call_args.kwargs.get("scope", "full")
            assert call_scope == "schema_only"

        asyncio.get_event_loop().run_until_complete(_test())


# ═══════════════════════════════════════════════════════════════════
# ValidationScope Enum Tests
# ═══════════════════════════════════════════════════════════════════

class TestValidationScope:
    """Tests for ValidationScope enum."""

    def test_all_scopes(self):
        from app.services.validation.unified_validator import ValidationScope
        assert ValidationScope.SCHEMA_ONLY.value == "schema_only"
        assert ValidationScope.BUSINESS_RULES.value == "business_rules"
        assert ValidationScope.SCORM_COMPLIANCE.value == "scorm_compliance"
        assert ValidationScope.ACCESSIBILITY.value == "accessibility"
        assert ValidationScope.FULL.value == "full"

    def test_from_string(self):
        from app.services.validation.unified_validator import ValidationScope
        assert ValidationScope("full") == ValidationScope.FULL
        assert ValidationScope("schema_only") == ValidationScope.SCHEMA_ONLY

    def test_invalid_scope(self):
        from app.services.validation.unified_validator import ValidationScope
        import pytest
        with pytest.raises(ValueError):
            ValidationScope("invalid")


# ═══════════════════════════════════════════════════════════════════
# UnifiedValidationResult Tests
# ═══════════════════════════════════════════════════════════════════

class TestUnifiedValidationResult:
    """Tests for the result model."""

    def test_default_valid(self):
        from app.services.validation.unified_validator import UnifiedValidationResult
        result = UnifiedValidationResult()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.info == []

    def test_metadata_present(self):
        from app.services.validation.unified_validator import UnifiedValidationResult
        result = UnifiedValidationResult()
        assert "validated_at" in result.metadata
        assert "schema_version" in result.metadata
        assert "pages_checked" in result.metadata
        assert "duration_ms" in result.metadata

    def test_with_errors(self):
        from app.services.validation.unified_validator import (
            UnifiedValidationResult, UnifiedValidationMessage
        )
        result = UnifiedValidationResult(
            is_valid=False,
            errors=[UnifiedValidationMessage(
                code="TEST_ERROR", field="test", message="Test error",
                severity="error"
            )],
        )
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].code == "TEST_ERROR"

    def test_model_serialization(self):
        from app.services.validation.unified_validator import (
            UnifiedValidationResult, UnifiedValidationMessage
        )
        result = UnifiedValidationResult(
            errors=[UnifiedValidationMessage(
                code="E1", field="f1", message="m1", severity="error"
            )],
            warnings=[UnifiedValidationMessage(
                code="W1", field="f2", message="m2", severity="warning",
                page_id="p1"
            )],
        )
        d = result.model_dump()
        assert d["is_valid"] is False
        assert len(d["errors"]) == 1
        assert len(d["warnings"]) == 1
        assert d["errors"][0]["code"] == "E1"
        assert d["warnings"][0]["page_id"] == "p1"


# ═══════════════════════════════════════════════════════════════════
# Router Tests
# ═══════════════════════════════════════════════════════════════════

class TestRouterValidateCourse:
    """Tests for the validate_course router endpoint."""

    def test_endpoint_exists(self):
        from app.routers.ai_tools import router
        paths = {r.path: r.methods for r in router.routes}
        assert "/api/v1/ai/tools/validate_course" in paths
        assert "POST" in paths["/api/v1/ai/tools/validate_course"]

    def test_request_schema(self):
        from app.routers.ai_tools import ValidateCourseRequest
        body = ValidateCourseRequest(session_id="sess-001")
        assert body.session_id == "sess-001"
        assert body.validation_scope == "full"

    def test_request_schema_with_scope(self):
        from app.routers.ai_tools import ValidateCourseRequest
        body = ValidateCourseRequest(
            session_id="sess-001",
            validation_scope="schema_only"
        )
        assert body.validation_scope == "schema_only"

    def test_endpoints_not_duplicated(self):
        """validate endpoint from AI-005 still exists."""
        from app.routers.ai_tools import router
        paths = {r.path for r in router.routes}
        assert "/api/v1/ai/tools/validate" in paths
        assert "/api/v1/ai/tools/validate_course" in paths
