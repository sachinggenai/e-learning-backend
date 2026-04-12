"""
Integration test: verify the exported accordion SCORM HTML matches the
preview/frontend data contract.

Key invariants checked:
- course_data.js contains every panel from data.panels
- index.html contains the JS rendering logic for accordions
  (aria-expanded, accordion-trigger, toggleAccordion wiring)
- Panel content is faithfully encoded in course_data.js (not escaped)
"""
import json
import re
import pytest

from app.models.course import Course
from app.services.scorm_export import SCORMExportService


ACCORDION_PANELS = [
    {"id": "p1", "title": "Introduction", "content": "<p>Welcome to the <b>course</b>.</p>"},
    {"id": "p2", "title": "Core Concepts", "content": "<ul><li>Concept A</li><li>Concept B</li></ul>"},
    {"id": "p3", "title": "Summary", "content": "Here is a summary."},
]


async def _noop_validate(*_a, **_kw):
    return


def _extract_course_data_js(package_dir):
    js_text = (package_dir / "course_data.js").read_text(encoding="utf-8")
    match = re.search(r"var courseData\s*=\s*(\{.*\});", js_text, re.DOTALL)
    assert match, "Could not find courseData assignment in course_data.js"
    return json.loads(match.group(1))


@pytest.mark.asyncio
async def test_accordion_data_in_course_js_matches_preview_contract(tmp_path, monkeypatch):
    """course_data.js must faithfully contain every panel from data.panels."""
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()

    service = SCORMExportService()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    course = Course(
        courseId="acc-integ-001",
        title="Accordion Integration Test",
        author="QA",
        templates=[
            {
                "id": "tpl-acc-preview",
                "type": "accordion",
                "order": 0,
                "title": "Module Sections",
                "data": {
                    "content": "Accordion fallback text",
                    "panels": ACCORDION_PANELS,
                },
            }
        ],
    )

    await service._create_content_html(package_dir, course)
    await service._create_course_data_js(package_dir, course)

    course_data = _extract_course_data_js(package_dir)
    templates = course_data.get("templates", [])
    assert len(templates) == 1
    tpl = templates[0]

    # 1. Template type is preserved
    assert tpl["type"] == "accordion"

    # 2. Template title matches
    assert tpl["title"] == "Module Sections"

    # 3. All panels are embedded
    panels = tpl.get("data", {}).get("panels", [])
    assert len(panels) == len(ACCORDION_PANELS), (
        f"Expected {len(ACCORDION_PANELS)} panels, found {len(panels)}"
    )

    # 4. Panel titles and content match exactly
    for i, expected_panel in enumerate(ACCORDION_PANELS):
        actual_panel = panels[i]
        assert actual_panel["title"] == expected_panel["title"], (
            f"Panel {i} title mismatch: expected '{expected_panel['title']}', got '{actual_panel['title']}'"
        )
        assert actual_panel["content"] == expected_panel["content"], (
            f"Panel {i} content mismatch"
        )


@pytest.mark.asyncio
async def test_accordion_player_js_has_required_rendering_hooks(tmp_path, monkeypatch):
    """index.html must contain the accordion rendering logic for all aria/interaction hooks."""
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()

    service = SCORMExportService()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    course = Course(
        courseId="acc-integ-002",
        title="Accordion Player Hooks",
        author="QA",
        templates=[
            {
                "id": "tpl-acc-hooks",
                "type": "accordion",
                "order": 0,
                "title": "Hooks Test",
                "data": {
                    "content": "fallback",
                    "panels": [
                        {"id": "p1", "title": "P1", "content": "Content 1"},
                        {"id": "p2", "title": "P2", "content": "Content 2"},
                    ],
                },
            }
        ],
    )

    await service._create_content_html(package_dir, course)
    html = (package_dir / "index.html").read_text(encoding="utf-8")

    # Player JS must contain accordion rendering function
    assert "renderAccordion: function(slide)" in html

    # Accessibility attributes written by the renderer
    assert 'aria-expanded="' in html
    assert 'accordion-trigger' in html

    # toggleAccordion interaction handler must be present
    assert "toggleAccordion: function(panelIndex)" in html
    assert "Player.toggleAccordion(" in html

    # Keyboard activation support
    assert "onActivationKey" in html
    assert "accordion" in html


@pytest.mark.asyncio
async def test_accordion_fallback_in_course_data_when_no_panels(tmp_path, monkeypatch):
    """When data.panels is empty, course_data.js still has the template with content field."""
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()

    service = SCORMExportService()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    course = Course(
        courseId="acc-fallback-001",
        title="Empty Accordion",
        author="QA",
        templates=[
            {
                "id": "tpl-acc-empty",
                "type": "accordion",
                "order": 0,
                "title": "Empty Sections",
                "data": {
                    "content": "This is the fallback paragraph text.",
                    "panels": [],
                },
            }
        ],
    )

    await service._create_content_html(package_dir, course)
    await service._create_course_data_js(package_dir, course)

    course_data = _extract_course_data_js(package_dir)
    tpl = course_data["templates"][0]

    assert tpl["type"] == "accordion"
    data = tpl.get("data", {})
    assert data.get("panels") == [] or "panels" in data
    assert "fallback paragraph text" in data.get("content", "")


@pytest.mark.asyncio
async def test_accordion_panel_html_content_is_preserved_in_course_data_js(tmp_path, monkeypatch):
    """Rich HTML in panel content must be preserved as-is in course_data.js, not escaped."""
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()

    service = SCORMExportService()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate)

    course = Course(
        courseId="acc-rich-001",
        title="Rich HTML Accordion",
        author="QA",
        templates=[
            {
                "id": "tpl-acc-rich",
                "type": "accordion",
                "order": 0,
                "title": "Rich Content",
                "data": {
                    "content": "fallback",
                    "panels": [
                        {"id": "r1", "title": "HTML Panel", "content": "<strong>Bold text</strong>"},
                    ],
                },
            }
        ],
    )

    await service._create_course_data_js(package_dir, course)

    js_text = (package_dir / "course_data.js").read_text(encoding="utf-8")

    # The raw HTML tags must appear in course_data.js (JSON-encoded form)
    # JSON-encodes < as \u003c or keeps as literal — either is fine as long as it's decodable
    course_data = _extract_course_data_js(package_dir)
    panel_content = course_data["templates"][0]["data"]["panels"][0]["content"]
    assert panel_content == "<strong>Bold text</strong>", (
        f"Panel HTML content was altered in course_data.js: {panel_content!r}"
    )


