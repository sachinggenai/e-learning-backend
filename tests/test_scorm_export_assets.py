from pathlib import Path
import io
import zipfile

import pytest

from app.models.course import Course
from app.services.scorm_export import SCORMExportService


class _Asset:
    def __init__(self, path: str, name: str, asset_type: str = "image"):
        self.path = path
        self.name = name
        self.type = asset_type


@pytest.mark.asyncio
async def test_copy_assets_copies_real_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    media_dir = tmp_path / "media" / "global" / "image"
    media_dir.mkdir(parents=True, exist_ok=True)
    source_file = media_dir / "sample.png"
    source_file.write_bytes(b"real-image-bytes")

    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True, exist_ok=True)

    service = SCORMExportService()
    assets = [
        _Asset(
            path="/api/v1/media/files/global/image/sample.png",
            name="Sample",
        )
    ]

    await service._copy_assets(package_dir, assets)

    copied_file = package_dir / "assets" / "sample.png"
    assert copied_file.exists()
    assert copied_file.read_bytes() == b"real-image-bytes"


@pytest.mark.asyncio
async def test_copy_assets_fails_for_missing_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True, exist_ok=True)

    service = SCORMExportService()
    assets = [_Asset(path="global/image/missing.png", name="Missing")]

    with pytest.raises(Exception, match="Asset copying failed"):
        await service._copy_assets(package_dir, assets)


@pytest.mark.asyncio
async def test_copy_assets_fails_for_duplicate_target_names(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    media_image = tmp_path / "media" / "global" / "image"
    media_video = tmp_path / "media" / "global" / "video"
    media_image.mkdir(parents=True, exist_ok=True)
    media_video.mkdir(parents=True, exist_ok=True)

    (media_image / "same.bin").write_bytes(b"image")
    (media_video / "same.bin").write_bytes(b"video")

    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True, exist_ok=True)

    service = SCORMExportService()
    assets = [
        _Asset(path="global/image/same.bin", name="One"),
        _Asset(path="global/video/same.bin", name="Two"),
    ]

    with pytest.raises(Exception, match="Duplicate asset filename"):
        await service._copy_assets(package_dir, assets)


@pytest.mark.asyncio
async def test_package_assets_writes_deterministic_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    media_image = tmp_path / "media" / "global" / "image"
    media_image.mkdir(parents=True, exist_ok=True)
    (media_image / "b.png").write_bytes(b"B")
    (media_image / "a.png").write_bytes(b"A")

    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True, exist_ok=True)

    service = SCORMExportService()
    assets = [
        _Asset(path="global/image/b.png", name="B", asset_type="image"),
        _Asset(path="global/image/a.png", name="A", asset_type="image"),
    ]

    manifest = await service._package_assets(package_dir, assets)

    assert manifest["assetCount"] == 2
    assert (package_dir / "asset_manifest.json").exists()
    assert all(a["packagePath"].startswith("assets/image-") for a in manifest["assets"])
    # Deterministic sort by source path/id means a.png should be first.
    assert manifest["assets"][0]["sourcePath"].endswith("a.png")


@pytest.mark.asyncio
async def test_generate_asset_files_xml_uses_packaged_asset_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    media_image = tmp_path / "media" / "global" / "image"
    media_image.mkdir(parents=True, exist_ok=True)
    (media_image / "img.png").write_bytes(b"X")

    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True, exist_ok=True)

    service = SCORMExportService()
    await service._package_assets(
        package_dir,
        [_Asset(path="global/image/img.png", name="Img", asset_type="image")],
    )

    xml = service._generate_asset_files_xml([])
    assert "assets/image-" in xml
    assert "img.png" not in xml


def test_remove_legacy_runtime_files_removes_only_stale_artifacts(tmp_path):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True, exist_ok=True)

    # Canonical runtime files that must remain
    for keep in ["index.html", "course_data.js", "styles.css", "scorm_wrapper.js"]:
        (package_dir / keep).write_text("ok", encoding="utf-8")

    # Stale artifacts
    for stale in ["index_legacy.html", "styles_v2.css", "course_data_v2.js"]:
        (package_dir / stale).write_text("stale", encoding="utf-8")
    (package_dir / "runtime").mkdir(parents=True, exist_ok=True)
    (package_dir / "runtime" / "old.js").write_text("stale", encoding="utf-8")

    service = SCORMExportService()
    service._remove_legacy_runtime_files(package_dir)

    assert (package_dir / "index.html").exists()
    assert (package_dir / "styles.css").exists()
    assert not (package_dir / "index_legacy.html").exists()
    assert not (package_dir / "styles_v2.css").exists()
    assert not (package_dir / "course_data_v2.js").exists()
    assert not (package_dir / "runtime").exists()


@pytest.mark.asyncio
async def test_generate_scorm_package_includes_asset_manifest_and_canonical_runtime(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    media_image = tmp_path / "media" / "global" / "image"
    media_image.mkdir(parents=True, exist_ok=True)
    (media_image / "logo.png").write_bytes(b"image-bytes")

    course = Course(
        courseId="smoke-assets-001",
        title="Smoke Assets",
        author="QA",
        templates=[
            {
                "id": "slide-1",
                "type": "content-text",
                "order": 0,
                "title": "Intro",
                "data": {"content": "Welcome"},
            }
        ],
        assets=[
            {
                "id": "asset-1",
                "path": "global/image/logo.png",
                "type": "image",
                "name": "Logo",
                "mimeType": "image/png",
            }
        ],
    )

    service = SCORMExportService()

    async def _valid(_course):
        return {"valid": True, "errors": [], "warnings": []}

    monkeypatch.setattr(service, "validate_for_export", _valid)

    package = await service.generate_scorm_package(course, include_assets=True)

    with zipfile.ZipFile(io.BytesIO(package.getvalue())) as zf:
        names = set(zf.namelist())
        assert "imsmanifest.xml" in names
        assert "index.html" in names
        assert "course_data.js" in names
        assert "styles.css" in names
        assert "scorm_wrapper.js" in names
        assert "asset_manifest.json" in names

        packaged_assets = [n for n in names if n.startswith("assets/image-")]
        assert len(packaged_assets) == 1

        # Legacy files should not be part of canonical runtime output.
        assert "styles_v2.css" not in names
        assert "course_data_v2.js" not in names
        assert "index_legacy.html" not in names


@pytest.mark.asyncio
async def test_create_content_html_includes_accessibility_and_scoped_css_runtime(
    tmp_path,
    monkeypatch,
):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True, exist_ok=True)

    course = Course(
        courseId="runtime-hooks-001",
        title="Runtime Hooks",
        author="QA",
        templates=[
            {
                "id": "tpl-tabs",
                "type": "tabs",
                "order": 0,
                "title": "Tabs",
                "customCss": ".x { color: red; }",
                "data": {
                    "content": "Tabs fallback",
                    "tabs": [
                        {"title": "One", "content": "A"},
                        {"title": "Two", "content": "B"},
                    ]
                },
            },
            {
                "id": "tpl-acc",
                "type": "accordion",
                "order": 1,
                "title": "Accordion",
                "data": {
                    "content": "Accordion fallback",
                    "panels": [
                        {"title": "P1", "content": "C1"},
                        {"title": "P2", "content": "C2"},
                    ]
                },
            },
        ],
    )

    service = SCORMExportService()

    async def _noop_validate_templates(_templates):
        return

    monkeypatch.setattr(service, "_validate_templates_for_scorm", _noop_validate_templates)

    await service._create_content_html(package_dir, course)

    index_html = (package_dir / "index.html").read_text(encoding="utf-8")
    assert "Player.onActivationKey(event," in index_html
    assert "Player.activateTab(" in index_html
    assert "Player.toggleAccordion(" in index_html
    assert "applyScopedCustomCss(slide);" in index_html
    assert "scopeCssToComponent: function(cssText, componentId)" in index_html
    assert "data-runtime-scoped-css" in index_html