"""Multi-tenancy context models.

TODO(TENANT): In production, this will be loaded from the tenant registry
service with real organization metadata, billing tier, and feature flags.

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR03_enriched.md
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class OrganizationContext(BaseModel):
    """Organization/tenant context for the current request.

    TODO(TENANT): In production, this will be loaded from the tenant
    registry service with real organization metadata, subscription
    status, billing tier, and feature flags.
    """

    organization_id: str = Field(
        default="00000000-0000-0000-0000-000000000100",
        description="UUID of the tenant organization",
    )
    name: str = Field(
        default="Mock Organization",
        description="Display name of the organization",
    )
    settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Organization-level settings and feature flags",
    )
    ai_features_enabled: bool = Field(
        default=True,
        description="Whether AI authoring is enabled for this tenant",
    )
    monthly_cost_cap_usd: float = Field(
        default=500.0,
        description="Monthly AI cost cap for this tenant (USD)",
    )
