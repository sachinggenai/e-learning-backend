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


@pytest.mark.asyncio
async def test_exported_runtime_wires_assessment_submit_actions(tmp_path, monkeypatch):
    service = SCORMExportService()

    async def _noop_validate(*args, **kwargs):
        return

    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    package_dir = tmp_path / "pkg-assessment-actions"
    package_dir.mkdir()

    course = Course(
        courseId="runtime-actions-1",
        title="Runtime Actions",
        author="QA",
        templates=[
            {
                "id": "tpl-mcq",
                "type": "mcq",
                "order": 0,
                "title": "MCQ",
                "data": {
                    "questions": [
                        {
                            "id": "q1",
                            "question": "2+2",
                            "options": [
                                {"id": "o1", "text": "4", "isCorrect": True},
                                {"id": "o2", "text": "3", "isCorrect": False},
                            ],
                        }
                    ]
                },
            },
            {
                "id": "tpl-ms",
                "type": "multiple-select",
                "order": 1,
                "title": "Multiple Select",
                "data": {
                    "questions": [
                        {
                            "id": "q2",
                            "question": "Select primes",
                            "options": [
                                {"id": "o1", "text": "2", "isCorrect": True},
                                {"id": "o2", "text": "4", "isCorrect": False},
                            ],
                        }
                    ]
                },
            },
            {
                "id": "tpl-fib",
                "type": "fill-in-blank",
                "order": 2,
                "title": "Fill Blank",
                "data": {
                    "question": "Capital of France?",
                    "correctAnswers": ["Paris"],
                },
            },
        ],
    )

    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")

    assert "data-action=\"submit-mcq\"" in html
    assert "data-action=\"submit-multiple-select\"" in html
    assert "data-action=\"check-fill-blank\"" in html
    assert "data-action=\"submit-final-assessment\"" in html

    assert "if (action === 'submit-mcq')" in html
    assert "if (action === 'submit-multiple-select')" in html
    assert "if (action === 'check-fill-blank')" in html
    assert "if (action === 'submit-final-assessment')" in html


@pytest.mark.asyncio
async def test_exported_runtime_enforces_final_assessment_finish_gate(tmp_path, monkeypatch):
    service = SCORMExportService()

    async def _noop_validate(*args, **kwargs):
        return

    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    package_dir = tmp_path / "pkg-finish-gate"
    package_dir.mkdir()

    course = Course(
        courseId="runtime-finish-1",
        title="Runtime Finish Gate",
        author="QA",
        templates=[
            {
                "id": "tpl-final",
                "type": "final-assessment",
                "order": 0,
                "title": "Final",
                "data": {
                    "passingScore": 70,
                    "questions": [
                        {
                            "id": "q1",
                            "type": "true-false",
                            "question": "Earth is round",
                            "correctAnswer": True,
                        }
                    ],
                },
            }
        ],
    )

    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")

    assert "finalAssessmentSubmissions" in html
    assert "failedFinalAssessments" in html
    assert "if (failedFinalAssessments.length > 0)" in html
    assert "Final assessment not passed" in html

    assert "SCORM.setValue('cmi.core.mastery_score'" in html
    assert "SCORM.setValue('cmi.core.lesson_status', passed ? 'passed' : 'failed')" in html
    assert "Final assessment present, preserving submitted pass/fail SCORM status" in html
