"""Deterministic asset packaging for SCORM export."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import mimetypes
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List


@dataclass
class PackagedAsset:
    """Resolved packaged asset metadata."""

    asset_id: str
    source_path: str
    package_path: str
    filename: str
    file_hash: str
    size: int
    mime_type: str
    asset_type: str


class AssetPackager:
    """Package assets in deterministic order and naming."""

    def __init__(self, resolve_source_path_fn):
        self._resolve_source_path_fn = resolve_source_path_fn

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _safe_extension(source: Path, mime_type: str) -> str:
        ext = source.suffix.lower()
        if ext:
            return ext
        guessed = mimetypes.guess_extension(mime_type or "")
        return guessed or ".bin"

    @staticmethod
    def _build_export_filename(asset_type: str, index: int, file_hash: str, ext: str) -> str:
        safe_type = (asset_type or "asset").replace("_", "-").replace(" ", "-")
        return f"{safe_type}-{index:04d}-{file_hash[:12]}{ext}"

    def package_assets(self, package_dir: Path, assets: List[Any]) -> List[PackagedAsset]:
        """Copy assets to package_dir/assets with deterministic names and order."""
        if not assets:
            return []

        assets_dir = package_dir / "assets"
        assets_dir.mkdir(exist_ok=True)

        # Stable sort: asset.id then path then name fallback.
        sorted_assets = sorted(
            assets,
            key=lambda a: (
                str(getattr(a, "id", "")),
                str(getattr(a, "path", "")),
                str(getattr(a, "name", "")),
            ),
        )

        packaged: List[PackagedAsset] = []
        used_filenames = set()

        for index, asset in enumerate(sorted_assets, start=1):
            asset_id = str(getattr(asset, "id", "asset-{index}"))
            raw_path = str(getattr(asset, "path", "")).strip()
            asset_type = str(getattr(asset, "type", "other") or "other")

            if not raw_path:
                raise ValueError(f"Asset {asset_id} has empty path")

            source_path = self._resolve_source_path_fn(raw_path)
            if not source_path.exists():
                raise FileNotFoundError(f"Asset source not found: {source_path}")

            mime_type = str(
                getattr(asset, "mimeType", None)
                or mimetypes.guess_type(str(source_path))[0]
                or "application/octet-stream"
            )
            file_hash = self._hash_file(source_path)
            ext = self._safe_extension(source_path, mime_type)
            filename = self._build_export_filename(asset_type, index, file_hash, ext)

            # Extremely unlikely, but keep deterministic uniqueness.
            if filename in used_filenames:
                filename = self._build_export_filename(asset_type, index, file_hash + str(index), ext)
            used_filenames.add(filename)

            target_path = assets_dir / filename
            shutil.copy2(source_path, target_path)

            packaged.append(
                PackagedAsset(
                    asset_id=asset_id,
                    source_path=str(source_path),
                    package_path=f"assets/{filename}",
                    filename=filename,
                    file_hash=file_hash,
                    size=target_path.stat().st_size,
                    mime_type=mime_type,
                    asset_type=asset_type,
                )
            )

        return packaged

    @staticmethod
    def write_asset_manifest(package_dir: Path, packaged_assets: List[PackagedAsset]) -> Dict[str, Any]:
        """Write asset_manifest.json and return its content."""
        manifest = {
            "version": "1.0",
            "assetCount": len(packaged_assets),
            "assets": [
                {
                    "assetId": a.asset_id,
                    "packagePath": a.package_path,
                    "filename": a.filename,
                    "sourcePath": a.source_path,
                    "mimeType": a.mime_type,
                    "size": a.size,
                    "type": a.asset_type,
                    "sha256": a.file_hash,
                }
                for a in packaged_assets
            ],
        }

        manifest_path = package_dir / "asset_manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return manifest
