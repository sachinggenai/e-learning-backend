"""Base builder interface for SCORM components."""
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseBuilder(ABC):
    """Base class for all SCORM component builders."""

    @abstractmethod
    async def build(self, context: Dict[str, Any]) -> str:
        """Build the component and return its content as string."""
        pass
