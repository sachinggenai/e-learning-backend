"""Mock Multi-Tenancy Service.

TODO(TENANT): Replace with real tenant infrastructure:
1. Tenant-aware database connections (schema-per-tenant or RLS)
2. Organization service for metadata, billing, and feature flags
3. Cross-tenant access prevention at the database level
4. Tenant-specific rate limiting and quota enforcement
5. Tenant provisioning and deprovisioning workflows

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR03_enriched.md
"""

import os
import logging
from typing import Optional

from fastapi import Request, HTTPException, Depends
from sqlalchemy import true as sa_true

from app.models.user_context import UserContext
from app.models.tenant import OrganizationContext
from app.dependencies.auth_dependencies import get_current_user

logger = logging.getLogger("ai_authoring")

_TENANT_MOCK_MODE = os.getenv("TENANT_MOCK_MODE", "enabled").lower() in (
    "enabled", "1", "true", "yes"
)

_ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
if _TENANT_MOCK_MODE and _ENVIRONMENT in ("staging", "production"):
    logger.critical(
        "TENANT_MOCK_MODE is ENABLED in %s environment! "
        "Cross-tenant isolation is NOT enforced in mock mode.",
        _ENVIRONMENT,
    )


async def get_current_organization(
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> OrganizationContext:
    """FastAPI dependency: return the current organization context.

    Usage:
        @router.get("/courses")
        async def list_courses(
            org: OrganizationContext = Depends(get_current_organization),
        ):
            # org.organization_id, org.name, org.settings available
            ...

    TODO(TENANT): Load from tenant registry, validate subscription
    is active, check feature flags for the organization.
    """
    return OrganizationContext(
        organization_id=user.organization_id,
        name=f"Mock Organization {user.organization_id[:8]}",
        settings={},
        ai_features_enabled=True,
        monthly_cost_cap_usd=500.0,
    )


def tenant_filter(organization_id: str):
    """Return a SQLAlchemy filter for tenant-scoped queries.

    In mock mode: returns a no-op filter (sa.true()).
    In production: returns Model.organization_id == organization_id.

    Usage:
        query = select(CourseRecord).where(tenant_filter(org_id))

    TODO(TENANT): Apply real tenant filtering via:
    1. schema_per_tenant: SET search_path = 'tenant_{org_id}'
    2. RLS: PostgreSQL Row-Level Security policy
    3. Application-level: .filter(Model.organization_id == org_id)
    """
    # TODO(TENANT): Return actual column filter when tenant columns exist
    # return ModelClass.organization_id == organization_id
    return sa_true()


def validate_same_tenant(user_org_id: str, resource_org_id: str) -> None:
    """Raise 403 if resource belongs to a different tenant.

    In mock mode: logs a WARNING but does NOT block access.
    In production: raises HTTPException(403).

    TODO(TENANT): Uncomment the HTTPException raise when real tenant
    enforcement is active. This is a HARD enforcement point.
    """
    if user_org_id != resource_org_id:
        logger.warning(
            "TENANT_ISOLATION_WARNING: user_org=%s accessing resource_org=%s. "
            "Mock mode allows this. "
            "TODO(TENANT): Will be blocked in production.",
            user_org_id,
            resource_org_id,
        )
        # TODO(TENANT): Uncomment when real tenant enforcement is active:
        # raise HTTPException(
        #     status_code=403,
        #     detail="Cross-tenant access denied",
        # )
