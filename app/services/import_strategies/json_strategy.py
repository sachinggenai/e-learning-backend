from __future__ import annotations
import io
import zipfile
from typing import Any, Dict, Iterable, List

from app.services.heuristic_parser import HeuristicParser
from app.services.import_strategies.base import StrategyResult, ImportStrategy


class JsonPayloadStrategy(ImportStrategy):
    """Extract JSON payloads embedded in JS/JSON/HTML files."""

    def __init__(self, max_files: int = 2000, max_file_bytes: int = 5_000_000):
        self.parser = HeuristicParser()
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes

    def supports(self, zip_bytes: bytes, entries: Iterable[str]) -> bool:
        # Support if we see any JS/JSON/HTML file names; deeper validation is
        # in analyze.
        for name in entries:
            lower = name.lower()
            if lower.endswith((".js", ".json", ".html")):
                return True
        return False

    async def analyze(
        self, zip_bytes: bytes, entries: Iterable[str]
    ) -> StrategyResult:
        payloads: List[Dict[str, Any]] = []
        warnings: List[str] = []

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
            if len(names) > self.max_files:
                raise ValueError("Archive contains too many files")

            for name in names:
                lower = name.lower()
                if not lower.endswith((".js", ".json", ".html")):
                    continue
                info = zf.getinfo(name)
                if info.file_size > self.max_file_bytes:
                    warnings.append(f"Skipped {name} due to size limit")
                    continue
                with zf.open(name) as fp:
                    try:
                        text = fp.read().decode("utf-8", errors="ignore")
                    except Exception:
                        warnings.append(f"Failed to read {name}")
                        continue
                try:
                    found = self.parser.extract_json_from_js(text)
                    payloads.extend(found)
                except Exception:
                    warnings.append(f"Failed to parse {name}")
                    continue

        if not payloads:
            raise ValueError("No JSON payloads found in package")

        course_data = payloads[0]
        return StrategyResult(
            course_data=course_data,
            warnings=warnings,
            strategy=self.__class__.__name__,
        )
