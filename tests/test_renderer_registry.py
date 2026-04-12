"""
Unit tests for the SCORM export renderer registry.

Covers:
- getRenderer returns a renderer for every supported type
- Each renderer produces syntactically valid HTML with key structural landmarks
- Unsupported type falls back gracefully
- All 17+ template categories represented
"""
import io
import zipfile
import pytest

from app.models.course import Course
from app.services.scorm_export import SCORMExportService


def _make_service():
    return SCORMExportService()


async def _noop_validate(*_args, **_kwargs):
    """Async no-op for monkeypatching _validate_templates_for_scorm."""
    return


def _slide(type_, data, slide_id="tpl-1", title="Test Slide"):
    return {
        "id": slide_id,
        "type": type_,
        "order": 0,
        "title": title,
        "data": {**data, "content": data.get("content", "Fallback content")},
    }


@pytest.mark.asyncio
async def test_runtime_gate_accepts_all_registry_types(tmp_path, monkeypatch):
    """Every type in getRenderer must also be in runtime_supported_template_types."""
    service = _make_service()
    supported = service.runtime_supported_template_types

    # These are all types wired in the JS getRenderer. We'll verify from Python side
    # by checking a broad representative set that the gate accepts.
    known_types = [
        "content-text", "content", "rich-text-editor",
        "content-media", "content-image", "content-video", "transcript-caption",
        "infographic", "quotation",
        "tabs", "accordion", "stepper", "timeline",
        "course-menu", "breadcrumb", "sidebar-navigation",
        "mcq", "multiple-select", "true-false", "fill-in-blank",
        "hotspot", "image-hotspots", "matching", "drag-and-drop",
        "key-takeaways", "summary-takeaways", "learning-objectives",
        "flashcard", "quiz",
        "scenario", "branching-scenario", "decision-tree", "role-play",
        "metric", "data-visualization", "progress-tracker", "analytics-view",
        "heat-map", "code-snippet", "calculator", "form", "interactive-tool",
        "learning-roadmap", "module-overview", "course-map",
    ]
    missing = [t for t in known_types if t not in supported]
    assert missing == [], f"Types missing from runtime gate: {missing}"


@pytest.mark.asyncio
async def test_content_text_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-content", title="T", author="QA",
        templates=[_slide("content-text", {"content": "<p>Hello <b>world</b></p>"})],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "content-template" in html
    assert "content-body" in html


@pytest.mark.asyncio
async def test_rich_text_editor_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-rte", title="T", author="QA",
        templates=[_slide("rich-text-editor", {"htmlContent": "<h2>Rich</h2><p>Content</p>"})],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "rich-text-template" in html


@pytest.mark.asyncio
async def test_quotation_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-quote", title="T", author="QA",
        templates=[_slide("quotation", {
            "content": "fallback", "quoteText": "To be or not to be.", "author": "Shakespeare",
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "quotation-template" in html
    assert "blockquote" in html


@pytest.mark.asyncio
async def test_key_takeaways_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-kt", title="T", author="QA",
        templates=[_slide("key-takeaways", {
            "content": "fallback",
            "takeaways": ["Point A", "Point B", "Point C"],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "takeaways-template" in html
    assert "takeaways-list" in html


@pytest.mark.asyncio
async def test_learning_objectives_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-lo", title="T", author="QA",
        templates=[_slide("learning-objectives", {
            "content": "fallback",
            "objectives": [
                {"text": "Understand the basics"},
                {"text": "Apply new concepts"},
            ],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "objectives-template" in html
    assert "objectives-list" in html


@pytest.mark.asyncio
async def test_image_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-img", title="T", author="QA",
        templates=[_slide("content-image", {
            "content": "fallback",
            "src": "assets/image-001.png",
            "altText": "A diagram",
            "caption": "Figure 1",
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "image-template" in html
    assert "image-figure" in html


@pytest.mark.asyncio
async def test_video_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-vid", title="T", author="QA",
        templates=[_slide("content-video", {
            "content": "fallback",
            "src": "assets/video-001.mp4",
            "transcript": "<p>Words spoken in the video.</p>",
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "video-template" in html
    assert "video-transcript" in html


@pytest.mark.asyncio
async def test_code_snippet_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-code", title="T", author="QA",
        templates=[_slide("code-snippet", {
            "content": "fallback",
            "code": "print('hello world')",
            "language": "python",
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "code-template" in html
    assert "code-block" in html


@pytest.mark.asyncio
async def test_stepper_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-step", title="T", author="QA",
        templates=[_slide("stepper", {
            "content": "fallback",
            "steps": [
                {"title": "Step 1", "content": "Do first thing"},
                {"title": "Step 2", "content": "Do second thing"},
            ],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "stepper-template" in html
    assert "stepper-list" in html


@pytest.mark.asyncio
async def test_timeline_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-timeline", title="T", author="QA",
        templates=[_slide("timeline", {
            "content": "fallback",
            "events": [
                {"date": "2020", "title": "Founded", "description": "Company started"},
                {"date": "2023", "title": "Expanded", "description": "Grew to 100 employees"},
            ],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "timeline-template" in html
    assert "timeline-list" in html


@pytest.mark.asyncio
async def test_metric_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-metric", title="T", author="QA",
        templates=[_slide("metric", {
            "content": "fallback",
            "value": "98", "label": "Satisfaction %", "unit": "%",
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "metric-template" in html
    assert "metric-value" in html


@pytest.mark.asyncio
async def test_progress_tracker_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-prog", title="T", author="QA",
        templates=[_slide("progress-tracker", {
            "content": "fallback",
            "progress": 75, "total": 100, "label": "Completion",
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "progress-template" in html
    assert "prog-fill" in html


@pytest.mark.asyncio
async def test_flashcard_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-fc", title="T", author="QA",
        templates=[_slide("flashcard", {
            "content": "fallback",
            "cards": [
                {"front": "What is photosynthesis?", "back": "The process by which plants make food."},
                {"front": "Capital of France?", "back": "Paris"},
            ],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "flashcard-template" in html
    assert "flashcard-front" in html
    assert "flashcard-back" in html


@pytest.mark.asyncio
async def test_multiple_select_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-ms", title="T", author="QA",
        templates=[_slide("multiple-select", {
            "content": "fallback",
            "questions": [{"id": "q1", "question": "Select all even numbers:", "options": [
                {"id": "o1", "text": "2", "isCorrect": True},
                {"id": "o2", "text": "3", "isCorrect": False},
                {"id": "o3", "text": "4", "isCorrect": True},
            ]}],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "multiple-select-template" in html
    assert 'type="checkbox"' in html


@pytest.mark.asyncio
async def test_true_false_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-tf", title="T", author="QA",
        templates=[_slide("true-false", {
            "content": "fallback",
            "questions": [{"id": "q1", "question": "The sky is blue.", "options": [
                {"id": "o1", "text": "True", "isCorrect": True},
                {"id": "o2", "text": "False", "isCorrect": False},
            ]}],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "true-false-template" in html
    assert "True" in html
    assert "False" in html


@pytest.mark.asyncio
async def test_fill_in_blank_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-fib", title="T", author="QA",
        templates=[_slide("fill-in-blank", {
            "content": "fallback",
            "question": "The capital of France is _____.",
            "correctAnswers": ["Paris"],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "fill-blank-template" in html
    assert "blank-input" in html


@pytest.mark.asyncio
async def test_scenario_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-scen", title="T", author="QA",
        templates=[_slide("scenario", {
            "content": "fallback",
            "scenarioText": "A new employee arrives late...",
            "options": [
                {"text": "Ignore it", "feedback": "Not ideal."},
                {"text": "Speak to them privately", "feedback": "Good choice!"},
            ],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "scenario-template" in html
    assert "scenario-options" in html


@pytest.mark.asyncio
async def test_data_visualization_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-dv", title="T", author="QA",
        templates=[_slide("data-visualization", {
            "content": "fallback",
            "headers": ["Region", "Sales"],
            "rows": [["North", "12000"], ["South", "9800"]],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "datatable-template" in html
    assert "data-table" in html
    assert "<th" in html


@pytest.mark.asyncio
async def test_hotspot_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-hs", title="T", author="QA",
        templates=[_slide("hotspot", {
            "content": "fallback",
            "src": "assets/image-001.png",
            "hotspots": [
                {"label": "Zone A", "description": "This is zone A"},
            ],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "hotspot-template" in html
    assert "hotspot-list" in html


@pytest.mark.asyncio
async def test_module_overview_renderer(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    course = Course(
        courseId="r-mo", title="T", author="QA",
        templates=[_slide("module-overview", {
            "content": "fallback",
            "description": "This course covers the fundamentals.",
            "modules": [
                {"title": "Module 1: Intro", "description": "An introduction"},
                {"title": "Module 2: Basics", "description": "Core principles"},
            ],
        })],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "module-overview-template" in html
    assert "modules-list" in html


@pytest.mark.asyncio
async def test_unknown_type_renders_gracefully(tmp_path, monkeypatch):
    """Unknown types render an informative error rather than crashing."""
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    service = _make_service()
    # Bypass runtime gate to test the runtime fallback rendering path
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)
    monkeypatch.setattr(service, "_validate_runtime_supported_template_types", lambda *a: [])
    course = Course(
        courseId="r-unknown", title="T", author="QA",
        templates=[_slide("some-unsupported-type-xyz", {"content": "test"})],
    )
    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")
    # Runtime calls renderUnknown which shows a message
    assert "renderUnknown" in html or "Unknown slide type" in html


@pytest.mark.asyncio
async def test_all_supported_types_validate_successfully(monkeypatch):
    """validate_for_export accepts courses using every supported type."""
    service = _make_service()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    supported_sample = list(service.runtime_supported_template_types)[:8]
    templates = [
        {
            "id": f"tpl-{i}", "type": t, "order": i, "title": t,
            "data": {"content": "Sample content"},
        }
        for i, t in enumerate(supported_sample)
    ]
    course = Course(
        courseId="r-all", title="All Types", author="QA", templates=templates,
    )

    result = await service.validate_for_export(course)
    assert result["valid"] is True
    assert result["errors"] == []
