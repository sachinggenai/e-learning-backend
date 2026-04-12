import pytest

from app.models.course import Course
from app.services.scorm_export import SCORMExportService


@pytest.mark.asyncio
async def test_validate_for_export_rejects_runtime_unsupported_template(monkeypatch):
    service = SCORMExportService()

    async def _noop_validate(*args, **kwargs):
        return

    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    course = Course(
        courseId="runtime-gate-1",
        title="Runtime Gate",
        author="QA",
        templates=[
            {
                "id": "tpl-1",
                "type": "unknown-x-template",
                "order": 0,
                "title": "Unknown",
                "data": {"content": "x"},
            }
        ],
    )

    result = await service.validate_for_export(course)

    assert result["valid"] is False
    assert any("not supported by current export runtime" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_validate_for_export_allows_runtime_supported_templates(monkeypatch):
    service = SCORMExportService()

    async def _noop_validate(*args, **kwargs):
        return

    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    course = Course(
        courseId="runtime-gate-2",
        title="Runtime Supported",
        author="QA",
        templates=[
            {
                "id": "tpl-1",
                "type": "content-text",
                "order": 0,
                "title": "Text",
                "data": {"content": "hello"},
            },
            {
                "id": "tpl-2",
                "type": "tabs",
                "order": 1,
                "title": "Tabs",
                "data": {"content": "fallback text is fine for validation"},
            },
            {
                "id": "tpl-3",
                "type": "mcq",
                "order": 2,
                "title": "MCQ",
                "data": {
                    "content": "Q",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "2+2",
                            "options": [
                                {"id": "o1", "text": "4", "isCorrect": True},
                                {"id": "o2", "text": "3", "isCorrect": False},
                            ],
                        }
                    ],
                },
            },
            {
                "id": "tpl-4",
                "type": "accordion",
                "order": 3,
                "title": "Accordion",
                "data": {
                    "content": "fallback",
                    "panels": [
                        {"id": "p1", "title": "One", "content": "Alpha"},
                        {"id": "p2", "title": "Two", "content": "Beta"},
                    ],
                },
            },
        ],
    )

    result = await service.validate_for_export(course)

    assert result["valid"] is True
    assert result["errors"] == []
