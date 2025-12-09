from __future__ import annotations
import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List

from app.services.import_strategies.base import StrategyResult, ImportStrategy


class Scorm12Strategy(ImportStrategy):
    """Parse SCORM 1.2 packages using imsmanifest.xml."""

    def __init__(self, max_files: int = 4000, max_file_bytes: int = 8_000_000):
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes

    def supports(self, zip_bytes: bytes, entries: Iterable[str]) -> bool:
        return any(
            name.lower().endswith("imsmanifest.xml") for name in entries
        )

    async def analyze(
        self, zip_bytes: bytes, entries: Iterable[str]
    ) -> StrategyResult:
        warnings: List[str] = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
            if len(names) > self.max_files:
                raise ValueError("Archive contains too many files")

            manifest_name = next(
                (
                    n
                    for n in names
                    if n.lower().endswith("imsmanifest.xml")
                ),
                None,
            )
            if not manifest_name:
                raise ValueError("SCORM manifest not found")

            manifest_bytes = zf.read(manifest_name)
            try:
                root = ET.fromstring(manifest_bytes)
            except ET.ParseError:
                raise ValueError("Invalid SCORM manifest")

            ns = {"imscp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2"}
            organization = self._select_organization(root, ns, warnings)
            title = (
                self._find_text(organization, "imscp:title", ns)
                if organization
                else None
            )
            resources = self._build_resource_map(root, ns)
            launches = (
                self._build_launch_list(organization, ns)
                if organization is not None
                else []
            )

            templates: List[Dict[str, Any]] = []
            for idx, launch in enumerate(launches):
                href = resources.get(launch)
                if not href:
                    warnings.append(f"Launch resource missing for {launch}")
                    continue
                content = self._read_text_file(zf, href)
                if content is None:
                    warnings.append(f"Failed to read launch file {href}")
                    continue
                templates.append(
                    {
                        "id": f"scorm12-{idx}",
                        "type": "content-text",
                        "title": href,
                        "order": idx,
                        "data": {"content": content},
                    }
                )

            course_data = {
                "courseId": title or "scorm12-import",
                "title": title or "Imported SCORM 1.2 Course",
                "templates": templates,
                "assets": [],
            }
            return StrategyResult(
                course_data=course_data,
                warnings=warnings,
                strategy=self.__class__.__name__,
            )

    @staticmethod
    def _find_text(
        root: ET.Element | None, path: str, ns: Dict[str, str]
    ) -> str | None:
        if root is None:
            return None
        node = root.find(path, ns)
        if node is not None and node.text:
            return node.text.strip()
        return None

    @staticmethod
    def _select_organization(
        root: ET.Element, ns: Dict[str, str], warnings: List[str]
    ) -> ET.Element | None:
        orgs = root.findall("./imscp:organizations/imscp:organization", ns)
        if not orgs:
            warnings.append(
                "No organization found in manifest; "
                "cannot determine launch page."
            )
            return None
        if len(orgs) > 1:
            warnings.append(
                "Multiple organizations found; defaulting to the first."
            )
        return orgs[0]

    @staticmethod
    def _build_resource_map(
        root: ET.Element, ns: Dict[str, str]
    ) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for res in root.findall("./imscp:resources/imscp:resource", ns):
            res_id = res.get("identifier")
            href = res.get("href")
            if res_id and href:
                mapping[res_id] = href
        return mapping

    @staticmethod
    def _build_launch_list(root: ET.Element, ns: Dict[str, str]) -> List[str]:
        launches: List[str] = []
        for item in root.findall(".//imscp:item", ns):
            identref = item.get("identifierref")
            if identref:
                launches.append(identref)
        return launches

    def _read_text_file(self, zf: zipfile.ZipFile, name: str) -> str | None:
        try:
            info = zf.getinfo(name)
        except KeyError:
            return None
        if info.file_size > self.max_file_bytes:
            return None
        try:
            with zf.open(name) as fp:
                return fp.read().decode("utf-8", errors="ignore")
        except Exception:
            return None
