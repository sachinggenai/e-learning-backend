from abc import ABC, abstractmethod
from typing import Dict, Any, List

from typing import Dict, Any, List


class BaseTemplateRenderer(ABC):
    """Base class for all template renderers."""

    def __init__(self, template_type: str):
        self.template_type = template_type

    @abstractmethod
    async def validate(self, data: Dict[str, Any]) -> bool:
        """Validate template data against schema."""
        pass

    @abstractmethod
    async def render(
        self, data: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """Render the template to HTML."""
        pass

    @abstractmethod
    async def get_assets(self, data: Dict[str, Any]) -> List[str]:
        """Get list of assets required by this template instance."""
        pass
