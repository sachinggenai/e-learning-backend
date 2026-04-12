import pytest

from app.services.export_validator import validate_course_for_export
from app.services.renderer_manifest import get_renderer_manifest


def _base_course(components):
    return {
        "courseId": "course-1",
        "title": "Validator Test",
        "pages": [
            {
                "pageId": "page-1",
                "title": "Page 1",
                "order": 0,
                "components": components,
            }
        ],
    }


def test_validator_fails_unknown_component_type():
    course = _base_course(
        [
            {
                "componentId": "c1",
                "componentType": "totally-unknown-template",
                "data": {"content": "x"},
            }
        ]
    )

    result = validate_course_for_export(course)

    assert result.isValid is False
    assert any(err.code == "UNSUPPORTED_COMPONENT_TYPE" for err in result.errors)


def test_validator_warns_when_component_uses_fallback():
    course = _base_course(
        [
            {
                "componentId": "c1",
                "componentType": "discussion-forum",
                "data": {"topics": ["a"]},
            }
        ]
    )

    result = validate_course_for_export(course)

    assert result.isValid is True
    assert any("fallback type" in warning for warning in result.warnings)


def test_validator_flags_missing_required_fields_for_tabs():
    course = _base_course(
        [
            {
                "componentId": "c1",
                "componentType": "tabs",
                "data": {},
            }
        ]
    )

    result = validate_course_for_export(course)

    assert result.isValid is False
    assert any(err.code == "MISSING_REQUIRED_FIELD" for err in result.errors)


def test_validator_allows_minimal_valid_tabs_component():
    course = _base_course(
        [
            {
                "componentId": "c1",
                "componentType": "tabs",
                "data": {"tabs": [{"title": "A", "content": "B"}]},
            }
        ]
    )

    result = validate_course_for_export(course)

    assert result.isValid is True
    assert result.unsupportedComponentCount == 0
    assert result.supportedComponentCount == 1


def _dummy_value(field_name: str):
    lower = field_name.lower()
    if "tab" in lower:
        return [{"title": "Tab", "content": "Body"}]
    if "panel" in lower:
        return [{"title": "Panel", "content": "Body"}]
    if "question" in lower:
        return [{"question": "Q", "options": [{"text": "A", "isCorrect": True}]}]
    if "option" in lower:
        return [{"text": "A", "isCorrect": True}]
    if "asset" in lower or "image" in lower or "video" in lower or "audio" in lower or "document" in lower:
        return "asset-1"
    if "url" in lower:
        return "https://example.com"
    if "items" in lower or "steps" in lower or "events" in lower or "modules" in lower:
        return [{"title": "Item"}]
    if "data" in lower:
        return [{"x": 1}]
    if "path" in lower:
        return [{"id": "n1"}]
    if "content" in lower or "text" in lower:
        return "sample"
    if "value" in lower:
        return 10
    return "sample"


@pytest.mark.parametrize(
    "component_type,entry",
    sorted(get_renderer_manifest().renderers.items(), key=lambda item: item[0]),
)
def test_validator_manifest_component_coverage(component_type, entry):
    data = {field: _dummy_value(field) for field in entry.requiredFields}
    component = {
        "componentId": f"cmp-{component_type}",
        "componentType": component_type,
        "data": data,
    }
    course = _base_course([component])

    result = validate_course_for_export(course)

    if entry.isExportable:
        assert result.isValid, f"Expected exportable type '{component_type}' to validate"
    else:
        # Non-exportable entries should be handled by fallback and warn.
        assert result.isValid
        assert any("fallback" in warning for warning in result.warnings)
