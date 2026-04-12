from __future__ import annotations
from typing import Iterable, List
import logging

from app.services.import_strategies.base import ImportStrategy, StrategyResult


logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Holds ordered import strategies and selects the first match."""

    def __init__(self, strategies: Iterable[ImportStrategy]):
        self._strategies: List[ImportStrategy] = list(strategies)

    def register(self, strategy: ImportStrategy) -> None:
        self._strategies.append(strategy)

    def _pick(
        self, zip_bytes: bytes, entries: Iterable[str]
    ) -> ImportStrategy | None:
        for strat in self._strategies:
            try:
                if strat.supports(zip_bytes, entries):
                    return strat
            except Exception as exc:
                # Continue scanning, but log diagnostics for triage.
                logger.warning(
                    "Import strategy '%s' failed during supports() check: %s",
                    strat.__class__.__name__,
                    exc,
                )
                continue
        return None

    async def analyze(
        self, zip_bytes: bytes, entries: Iterable[str]
    ) -> StrategyResult:
        strategy = self._pick(zip_bytes, entries)
        if not strategy:
            raise ValueError("No import strategy matched the uploaded package")
        return await strategy.analyze(zip_bytes, entries)
