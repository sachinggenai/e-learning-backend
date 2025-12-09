import io
import json
import zipfile
import pytest

from app.services.import_strategies.registry import StrategyRegistry
from app.services.import_strategies.json_strategy import JsonPayloadStrategy
from app.services.import_strategies.scorm12_strategy import Scorm12Strategy


def build_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_json_strategy_selected_and_parsed():
    payload = {"courseId": "c1", "title": "T", "templates": []}
    payload_json = json.dumps(payload)
    entries = {
      "course.js": f"const data = {payload_json};",
    }
    zip_bytes = build_zip(entries)

    registry = StrategyRegistry([Scorm12Strategy(), JsonPayloadStrategy()])
    result = await registry.analyze(zip_bytes, entries.keys())

    assert result.course_data.get("courseId") == "c1"
    assert result.course_data.get("templates") == []


@pytest.mark.asyncio
async def test_scorm12_strategy_selected_and_parsed():
    manifest = """
    <manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
      <organizations>
        <organization identifier="ORG1">
          <title>Sample SCORM</title>
          <item identifier="ITEM1" identifierref="RES1" />
        </organization>
      </organizations>
      <resources>
        <resource identifier="RES1" href="launch.html" />
      </resources>
    </manifest>
    """
    launch_html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
    entries = {
        "imsmanifest.xml": manifest,
        "launch.html": launch_html,
    }
    zip_bytes = build_zip(entries)

    registry = StrategyRegistry([Scorm12Strategy(), JsonPayloadStrategy()])
    result = await registry.analyze(zip_bytes, entries.keys())

    assert result.course_data.get("title") == "Sample SCORM"
    templates = result.course_data.get("templates") or []
    assert len(templates) == 1
    assert templates[0]["type"] == "content-text"
    assert "Hello" in templates[0]["data"]["content"]
    assert result.strategy == "Scorm12Strategy"


@pytest.mark.asyncio
async def test_no_matching_strategy_raises():
    entries = {"readme.txt": "nothing here"}
    zip_bytes = build_zip(entries)

    registry = StrategyRegistry([Scorm12Strategy(), JsonPayloadStrategy()])
    with pytest.raises(ValueError):
        await registry.analyze(zip_bytes, entries.keys())


@pytest.mark.asyncio
async def test_scorm12_missing_href_warns():
    manifest = """
    <manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
      <organizations>
        <organization identifier="ORG1">
          <title>Missing Href Course</title>
          <item identifier="ITEM1" identifierref="RES1" />
        </organization>
      </organizations>
      <resources>
        <resource identifier="RES1" />
      </resources>
    </manifest>
    """
    entries = {
        "imsmanifest.xml": manifest,
    }
    zip_bytes = build_zip(entries)

    registry = StrategyRegistry([Scorm12Strategy(), JsonPayloadStrategy()])
    result = await registry.analyze(zip_bytes, entries.keys())

    assert result.course_data.get("title") == "Missing Href Course"
    assert result.course_data.get("templates") == []
    assert result.strategy == "Scorm12Strategy"
    assert any("Launch resource missing" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_scorm12_multiple_orgs_uses_first():
    manifest = """
    <manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
      <organizations>
        <organization identifier="ORG1">
          <title>Org One</title>
          <item identifier="ITEM1" identifierref="RES1" />
        </organization>
        <organization identifier="ORG2">
          <title>Org Two</title>
          <item identifier="ITEM2" identifierref="RES2" />
        </organization>
      </organizations>
      <resources>
        <resource identifier="RES1" href="launch1.html" />
        <resource identifier="RES2" href="launch2.html" />
      </resources>
    </manifest>
    """
    entries = {
        "imsmanifest.xml": manifest,
        "launch1.html": "<html><body>One</body></html>",
        "launch2.html": "<html><body>Two</body></html>",
    }
    zip_bytes = build_zip(entries)

    registry = StrategyRegistry([Scorm12Strategy(), JsonPayloadStrategy()])
    result = await registry.analyze(zip_bytes, entries.keys())

    assert result.course_data.get("title") == "Org One"
    templates = result.course_data.get("templates") or []
    assert len(templates) == 1
    assert "One" in templates[0]["data"]["content"]
    assert result.strategy == "Scorm12Strategy"
