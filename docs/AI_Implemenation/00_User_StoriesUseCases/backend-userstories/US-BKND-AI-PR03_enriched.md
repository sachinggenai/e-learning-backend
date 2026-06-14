# US-BKND-AI-PR03 — Mock Multi-Tenancy Context

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 2
**Sprint:** 0 (Foundation)
**Depends On:** US-BKND-AI-PR01
**Unlocks:** ALL AI stories that scope data by organization

---

## 1. Functional Specification

### 1.1 User Story

As a **Backend Engineer building AI features**, I want a mock multi-tenancy service that provides tenant-scoped database queries and organization context, so that AI sessions, proposals, RAG queries, and audit logs are properly isolated by organization without waiting for the real tenant infrastructure.

### 1.2 Functional Requirements

**FR-1: Organization Context from User**
The system MUST extract `organization_id` from the current `UserContext` and provide it as a FastAPI dependency (`get_current_organization`).

**FR-2: Tenant-Scoped Query Helper**
The system MUST provide `tenant_filter(organization_id)` that returns a SQLAlchemy filter condition for scoping queries to a specific tenant. In mock mode, this is a pass-through. `# TODO(TENANT):` markers for real RLS/tenant column filtering.

**FR-3: Cross-Tenant Access Prevention**
The system MUST provide `validate_same_tenant(user_org_id, resource_org_id)` that raises 403 if the organization IDs don't match. In mock mode, this is a warning-only pass-through. `# TODO(TENANT):` for real enforcement.

**FR-4: Tenant Configuration Header**
Read `X-Organization-ID` header. Mock default: `00000000-0000-0000-0000-000000000100`.

**FR-5: Organization Metadata Resolver**
`get_organization(org_id)` returns a mock organization object with `id`, `name`, `settings`. `# TODO(TENANT):` for real organization service.

---

## 2. Technical Specification

### 2.1 `app/models/tenant.py`

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class OrganizationContext(BaseModel):
    """Organization/tenant context for the current request.

    TODO(TENANT): In production, this will be loaded from the tenant registry
    service with real organization metadata, billing tier, and feature flags.
    """
    organization_id: str
    name: str = "Mock Organization"
    settings: Dict[str, Any] = Field(default_factory=dict)
    ai_features_enabled: bool = True
    monthly_cost_cap_usd: float = 500.0
```

### 2.2 `app/services/ai/mock_tenancy.py`

```python
"""
Mock Multi-Tenancy Service

TODO(TENANT): Replace with real tenant infrastructure:
1. Tenant-aware database connections (schema-per-tenant or RLS)
2. Organization service for metadata, billing, and feature flags
3. Cross-tenant access prevention at the database level
4. Tenant-specific rate limiting and quota enforcement
5. Tenant provisioning and deprovisioning workflows
"""

import os
from fastapi import Request, HTTPException, Depends
from app.models.user_context import UserContext
from app.models.tenant import OrganizationContext
from app.dependencies.auth_dependencies import get_current_user

_TENANT_MOCK_MODE = os.getenv("TENANT_MOCK_MODE", "enabled").lower() in ("enabled", "1", "true", "yes")


async def get_current_organization(
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> OrganizationContext:
    """FastAPI dependency: return the current organization context.

    TODO(TENANT): Load from tenant registry, validate subscription is active,
    check feature flags for the organization.
    """
    return OrganizationContext(
        organization_id=user.organization_id,
        name=f"Mock Organization {user.organization_id[:8]}",
        settings={},
        ai_features_enabled=True,
        monthly_cost_cap_usd=500.0,
    )


def tenant_filter(organization_id: str):
    """Return SQLAlchemy filter for tenant-scoped queries.

    TODO(TENANT): Apply real tenant filtering via:
    1. schema_per_tenant: SET search_path = 'tenant_{org_id}'
    2. RLS: WHERE organization_id = :org_id (PostgreSQL Row-Level Security)
    3. Application-level: add .filter(Model.organization_id == org_id)
    """
    import sqlalchemy as sa
    # TODO(TENANT): This is a no-op filter. Replace with real column filter.
    return sa.true()


def validate_same_tenant(user_org_id: str, resource_org_id: str) -> None:
    """Raise 403 if resource belongs to a different tenant.

    TODO(TENANT): In production, this is a hard enforcement point.
    In mock mode, it only logs a warning.
    """
    if user_org_id != resource_org_id:
        import logging
        logger = logging.getLogger("ai_authoring")
        logger.warning(
            "TENANT_ISOLATION_WARNING: user_org=%s accessing resource_org=%s. "
            "Mock mode allows this. TODO(TENANT): Will be blocked in production.",
            user_org_id, resource_org_id,
        )
        # TODO(TENANT): Uncomment this when real tenant enforcement is active:
        # raise HTTPException(status_code=403, detail="Cross-tenant access denied")
```

---

## 6. Validation & Testing

- TC-PR03-01: `get_current_organization()` returns org context matching user's org_id
- TC-PR03-02: `tenant_filter()` returns a SQLAlchemy filter expression
- TC-PR03-03: `validate_same_tenant()` logs warning but does not raise for mismatched orgs (mock mode)
- TC-PR03-04: `TENANT_MOCK_MODE=disabled` raises 501

---

## 7. Definition of Done

- [ ] `OrganizationContext` model defined in `app/models/tenant.py`
- [ ] `mock_tenancy.py` implemented with all 3 functions
- [ ] All functions have `# TODO(TENANT):` comments
- [ ] `TENANT_MOCK_MODE` env var honored
- [ ] Unit tests pass (4 scenarios)
- [ ] Code reviewed

---

## 8. Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| PR03-T1 | Create `app/models/tenant.py` with `OrganizationContext` | Backend | 0.5h | PR01-T1 |
| PR03-T2 | Create `app/services/ai/mock_tenancy.py` with all functions | Backend | 1h | PR03-T1 |
| PR03-T3 | Add `TENANT_MOCK_MODE` env var | Backend | 0.5h | PR03-T2 |
| PR03-T4 | Write 4 unit tests | Backend | 1h | PR03-T2 |
| PR03-T5 | Code review | Lead | 0.5h | PR03-T4 |

---

---