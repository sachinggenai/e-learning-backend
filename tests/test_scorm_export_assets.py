from pathlib import Path

import pytest

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