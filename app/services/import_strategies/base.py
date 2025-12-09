from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Protocol


@dataclass
class StrategyResult:
    course_data: Dict[str, Any]
    warnings: Iterable[str]
    strategy: str
    assets: Dict[str, Any] | None = None


class ImportStrategy(Protocol):
    """Pluggable import strategy contract."""

    def supports(self, zip_bytes: bytes, entries: Iterable[str]) -> bool:
        ...

    async def analyze(
        self, zip_bytes: bytes, entries: Iterable[str]
    ) -> StrategyResult:
        ...
