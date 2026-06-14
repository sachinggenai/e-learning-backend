# Prerequisite Mock Services — Auth, AuthZ, Multi-Tenancy

**Status:** PRE-REQUISITE — Must complete before any AI user story
**Version:** 1.0.0
**Date:** 2026-06-14

---

## Rationale

The current codebase (`app/main.py`) has **only CORS middleware**. There is no:

- Authentication (no JWT, OAuth, API keys, or session tokens)
- Authorization (no role-based access, no permission checks)
- Multi-tenancy (no `organization_id` or `tenant_id` in ANY model)
- User identity (no `user_id`, `created_by`, or user context in requests)

**Every AI user story (US-AI-001 through US-AI-050) depends on these capabilities.** Without them, AI sessions can't be scoped, proposals can't be owned, audit logs can't attribute actions, and tenant data can't be isolated.

These 5 prerequisite stories provide **mock/stub implementations** that:

1. Return deterministic mock data based on HTTP headers
2. Use `# TODO(AUTH):` comments to mark where real implementations will be plugged in
3. Are sufficient for developing and testing all AI stories
4. Can be replaced with real auth/authz/tenant services without changing any AI story code

---

## Dependency Impact

```
US-AI-PR01 (Mock Auth)
    |
    v
US-AI-PR02 (Mock AuthZ)  <── US-AI-PR03 (Mock Tenancy)
    |                            |
    v                            v
US-AI-PR04 (Mock Session MW)  US-AI-PR05 (Mock User/Org Resolver)
    |                            |
    +────────────┬───────────────+
                 |
                 v
         ALL AI USER STORIES
         (US-AI-001 through US-AI-050)
```

**No AI story should be started until these 5 prerequisites are complete.**

---

## Mock Data Contract

All mock services use HTTP headers to receive identity context. In production, these will be replaced by JWT claims / session tokens.

| Header | Type | Default | Description |
|---|---|---|---|
| `X-User-ID` | UUID string | `00000000-0000-0000-0000-000000000001` | Mock user identity |
| `X-Organization-ID` | UUID string | `00000000-0000-0000-0000-000000000100` | Mock tenant/organization |
| `X-User-Role` | enum string | `instructor` | One of: `instructor`, `reviewer`, `admin`, `learner` |
| `X-User-Email` | email string | `mock.instructor@example.com` | Mock user email for audit logs |
| `Authorization` | string | `Mock session-00000000-0000-0000-0000-000000000099` | Session auth header (for session-scoped routes) |

---

---

# US-AI-PR01 — Mock Authentication Service

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 3
**Sprint:** 0 (Foundation)
**Depends On:** None
**Unlocks:** US-AI-PR02, US-AI-PR04, ALL AI stories

---

## 1. Functional Specification

### 1.1 User Story

As a **Backend Engineer building AI features**, I want a mock authentication service that accepts identity headers and returns a validated user context, so that I can develop and test AI session creation, proposal ownership, and audit attribution without waiting for the real authentication system to be built.

### 1.2 Functional Requirements

**FR-1: Header-Based Identity Extraction**
The system MUST extract user identity from `X-User-ID`, `X-Organization-ID`, `X-User-Role`, and `X-User-Email` HTTP request headers. If headers are missing, the system MUST use sensible defaults (see Mock Data Contract above).

**FR-2: User Context Object**
The system MUST produce a `UserContext` Pydantic model containing `user_id: str`, `organization_id: str`, `role: UserRole`, `email: str`, and `is_authenticated: bool`.

**FR-3: FastAPI Dependency Injection**
The system MUST expose `get_current_user()` as a FastAPI dependency that can be injected into any route handler. `Depends(get_current_user)` MUST return a `UserContext`.

**FR-4: TODO Markers for Real Auth**
Every function, class, and configuration point MUST contain `# TODO(AUTH):` comments explaining what the real implementation will need (JWT validation, OAuth flow, token refresh, etc.).

**FR-5: Configurable Mock Mode**
The system MUST read `AUTH_MOCK_MODE=enabled|disabled` from environment. When `disabled`, the service MUST return a clear error indicating real auth is not yet implemented. Default: `enabled`.

**FR-6: User Role Enum**
The system MUST define `UserRole` enum with values: `INSTRUCTOR`, `REVIEWER`, `ADMIN`, `LEARNER`.

**FR-7: Tenant-Scoped User Context**
The `UserContext` MUST include `organization_id` sourced from the `X-Organization-ID` header so that downstream multi-tenancy filtering can use it.

**FR-8: Audit Trail Attribution**
Every request MUST attach the `UserContext` to `request.state.user_context` so that audit logging middleware can access it without re-parsing headers.

### 1.3 User Flow

**Happy Path:**
1. Client sends `GET /api/v1/courses` with headers: `X-User-ID: user-123`, `X-Organization-ID: org-456`, `X-User-Role: instructor`
2. `get_current_user()` dependency extracts headers and returns `UserContext(user_id="user-123", organization_id="org-456", role=INSTRUCTOR, ...)`
3. Route handler receives the `UserContext` and uses `user_context.user_id` and `user_context.organization_id` for filtering

**Alternate (defaults):**
1. Client sends request with NO identity headers
2. `get_current_user()` returns defaults: `UserContext(user_id="00000000-...-0001", organization_id="00000000-...-0100", role=INSTRUCTOR, ...)`
3. Request proceeds with mock identity

**Error (mock mode disabled):**
1. `AUTH_MOCK_MODE=disabled`
2. Any call to `get_current_user()` raises `HTTPException(501, "Real authentication not yet implemented")`

---

## 2. Technical Specification

### 2.1 File Structure

```
app/
  services/
    ai/                          # TODO(AUTH): rename to app/services/auth/ when real auth is built
      mock_auth.py               # Mock authentication service (this story)
      __init__.py
  models/
    user_context.py              # UserContext Pydantic model
  dependencies/
    __init__.py
    auth_dependencies.py         # FastAPI dependency injection points
```

### 2.2 `app/models/user_context.py`

```python
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field

# TODO(AUTH): When real auth is implemented, extend this model with
# JWT claims, token expiry, refresh token, and MFA status.

class UserRole(str, Enum):
    """User roles for authorization decisions."""
    INSTRUCTOR = "instructor"   # Can author courses and use AI features
    REVIEWER = "reviewer"       # Can review and validate content
    ADMIN = "admin"             # Can manage tenants, audit, configure
    LEARNER = "learner"         # Read-only access to published courses

class UserContext(BaseModel):
    """Identity context extracted from the current request.

    TODO(AUTH): In production, this will be populated from JWT claims
    or session tokens, not from bare HTTP headers.
    """
    user_id: str = Field(
        default="00000000-0000-0000-0000-000000000001",
        description="UUID of the authenticated user"
    )
    organization_id: str = Field(
        default="00000000-0000-0000-0000-000000000100",
        description="UUID of the user's active organization/tenant"
    )
    role: UserRole = Field(
        default=UserRole.INSTRUCTOR,
        description="User's role within the organization"
    )
    email: str = Field(
        default="mock.instructor@example.com",
        description="User's email address (for audit logs)"
    )
    is_authenticated: bool = Field(
        default=True,
        description="Whether the user passed authentication"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def can_author(self) -> bool:
        return self.role in (UserRole.INSTRUCTOR, UserRole.ADMIN)
```

### 2.3 `app/services/ai/mock_auth.py`

```python
"""
Mock Authentication Service

TODO(AUTH): This entire module is a MOCK. Replace with real authentication
when the auth system is built. Expected replacement points:

1. Replace header-based identity extraction with JWT Bearer token validation
2. Add OAuth2 password flow / OpenID Connect integration
3. Add token refresh and revocation
4. Add MFA challenge/response
5. Add session management with Redis-backed session store
6. Add rate limiting on auth endpoints
7. Add audit logging for login/logout/failed attempts

For now, this mock service enables AI feature development to proceed
without blocking on auth infrastructure.
"""

import os
from typing import Optional
from fastapi import Request, HTTPException, Depends
from app.models.user_context import UserContext, UserRole

# TODO(AUTH): Move to app/core/config.py when real config system is built
_MOCK_MODE = os.getenv("AUTH_MOCK_MODE", "enabled").lower() in ("enabled", "1", "true", "yes")

# TODO(AUTH): Replace with JWT public key / JWKS endpoint URL
_JWT_SECRET_PLACEHOLDER = "TODO_AUTH_REPLACE_WITH_REAL_JWT_SECRET"


def _extract_user_context_from_headers(request: Request) -> UserContext:
    """Extract user identity from HTTP headers.

    TODO(AUTH): Replace this entire function with JWT Bearer token
    validation. The JWT will contain user_id, org_id, role, and email
    as claims. Token signature will be verified against the auth
    provider's public key.
    """
    user_id = request.headers.get("X-User-ID", "00000000-0000-0000-0000-000000000001")
    org_id = request.headers.get("X-Organization-ID", "00000000-0000-0000-0000-000000000100")
    role_str = request.headers.get("X-User-Role", "instructor")
    email = request.headers.get("X-User-Email", "mock.instructor@example.com")

    try:
        role = UserRole(role_str.lower())
    except ValueError:
        role = UserRole.INSTRUCTOR

    return UserContext(
        user_id=user_id,
        organization_id=org_id,
        role=role,
        email=email,
        is_authenticated=True,
    )


async def get_current_user(request: Request) -> UserContext:
    """FastAPI dependency: extract and return the current user context.

    Usage:
        @router.get("/courses")
        async def list_courses(user: UserContext = Depends(get_current_user)):
            ...

    TODO(AUTH): Replace header extraction with JWT Bearer token validation.
    The dependency will:
    1. Extract the Authorization: Bearer <token> header
    2. Validate the JWT signature against the auth provider's JWKS
    3. Check token expiry, issuer, audience claims
    4. Return UserContext populated from JWT claims
    """
    if not _MOCK_MODE:
        # TODO(AUTH): When real auth is implemented, remove this gate.
        # The real auth dependency will validate JWTs and never reach here.
        raise HTTPException(
            status_code=501,
            detail="Real authentication not yet implemented. "
                   "Set AUTH_MOCK_MODE=enabled to use mock auth, or "
                   "implement the auth service at app/services/auth/."
        )

    user_context = _extract_user_context_from_headers(request)

    # Attach to request state for downstream middleware usage
    # TODO(AUTH): This will be done by the auth middleware, not here
    request.state.user_context = user_context

    return user_context


# TODO(AUTH): Add these real auth dependencies:
# async def get_current_active_user(user: UserContext = Depends(get_current_user)) -> UserContext:
#     """Require an authenticated, non-disabled user."""
#     # Check user is not disabled / banned / locked out
#     pass
#
# async def get_current_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
#     """Require admin role."""
#     # Check user.role == UserRole.ADMIN
#     pass
```

### 2.4 `app/dependencies/auth_dependencies.py`

```python
"""
FastAPI dependency injection points for authentication.

TODO(AUTH): This file re-exports mock dependencies. When real auth is
implemented, update the import paths to point to app/services/auth/
instead of app/services/ai/mock_auth.py.
"""

# TODO(AUTH): Change these imports when real auth is built
# from app.services.auth.dependencies import get_current_user, get_current_admin
from app.services.ai.mock_auth import get_current_user

__all__ = ["get_current_user"]
```

### 2.5 Environment Variables

```bash
# .env.example additions

# ── Authentication ──────────────────────────────────────────────
# TODO(AUTH): Replace mock auth with real JWT/OAuth configuration.
# See app/services/ai/mock_auth.py for all TODO(AUTH) markers.
AUTH_MOCK_MODE=enabled              # enabled | disabled
# AUTH_JWT_SECRET=                  # TODO(AUTH): JWT signing secret (HS256/RS256)
# AUTH_JWKS_URL=                    # TODO(AUTH): JWKS endpoint URL for RS256
# AUTH_TOKEN_EXPIRY_MINUTES=60      # TODO(AUTH): Access token lifetime
# AUTH_REFRESH_TOKEN_EXPIRY_DAYS=7  # TODO(AUTH): Refresh token lifetime
# AUTH_ISSUER=elearning-backend     # TODO(AUTH): JWT iss claim
```

---

## 3. Non-Functional Requirements

### 3.1 Performance
- `get_current_user()` dependency MUST complete in < 1ms (header parsing only in mock mode)
- In production: JWT validation target < 5ms (cached JWKS)

### 3.2 Security
- Mock mode MUST NOT be enabled in production (`AUTH_MOCK_MODE` must be validated at startup)
- Mock mode MUST log a CRITICAL warning when enabled in non-development environments
- Headers used in mock mode MUST be stripped by API gateway in production

### 3.3 Reliability
- Default values MUST be provided for all missing headers (no 500 errors for missing headers in mock mode)
- `UserContext` model MUST be serializable for audit log inclusion

---

## 4. Current State Assessment

### 4.1 What Exists
- `app/utils/feature_flags.py` — feature flag system (can gate auth mock mode)
- `app/main.py` — CORS middleware only, no auth middleware
- FastAPI dependency injection infrastructure

### 4.2 What Must Be Built (Net-New)
- `app/models/user_context.py` — UserContext and UserRole models
- `app/services/ai/mock_auth.py` — Mock authentication service
- `app/dependencies/auth_dependencies.py` — Dependency injection exports
- `app/dependencies/__init__.py` — Package init

### 4.3 What Must Be Modified
- `app/main.py` — Nothing directly (mock auth is injected per-route via Depends)
- `.env.example` — Add AUTH_MOCK_MODE and TODO auth variables

---

## 5. Expansion Points

### 5.1 Technical Expansion
1. Replace header-based identity with JWT Bearer token validation (search for all `TODO(AUTH)` markers)
2. Add OAuth2 / OpenID Connect provider integration
3. Add Redis-backed session store for token blacklisting

### 5.2 Functional Expansion
1. Add `get_current_active_user()` dependency (checks account status)
2. Add `get_current_admin()` dependency (role-gated)
3. Add `require_permission(permission: str)` dependency factory

---

## 6. Validation & Testing

### 6.1 Unit Tests
```python
# tests/test_mock_auth.py

def test_get_current_user_with_all_headers():
    """User context is built from all provided headers."""
    # Build mock request with X-User-ID, X-Organization-ID, X-User-Role, X-User-Email
    # Expect UserContext with those exact values

def test_get_current_user_with_missing_headers_uses_defaults():
    """Missing headers fall back to default mock values."""
    # Build request with NO identity headers
    # Expect default user_id="0000...0001", org_id="0000...0100", role=INSTRUCTOR

def test_get_current_user_invalid_role_falls_back_to_instructor():
    """Invalid role string defaults to INSTRUCTOR."""
    # Header X-User-Role: "superuser" (not in enum)
    # Expect role=INSTRUCTOR

def test_get_current_user_mock_mode_disabled_raises_501():
    """When AUTH_MOCK_MODE=disabled, the dependency raises 501."""
    # Set env mock mode to disabled, attempt get_current_user
    # Expect HTTPException(501)

def test_user_context_is_admin_property():
    """is_admin returns True only for ADMIN role."""
    # UserContext(role=ADMIN).is_admin == True
    # UserContext(role=INSTRUCTOR).is_admin == False
```

### 6.2 Integration Tests
```python
# tests/test_auth_integration.py

def test_route_with_auth_dependency_receives_user_context():
    """A route using Depends(get_current_user) receives the context."""
    # Create test route with Depends(get_current_user)
    # Send request with headers, assert response includes user_id

def test_user_context_attached_to_request_state():
    """UserContext is available on request.state after dependency runs."""
    # Middleware/route can access request.state.user_context
```

---

## 7. Definition of Done

- [ ] `UserContext` and `UserRole` models defined in `app/models/user_context.py`
- [ ] `app/services/ai/mock_auth.py` implemented with header extraction
- [ ] `get_current_user()` FastAPI dependency working
- [ ] `AUTH_MOCK_MODE` environment variable honored
- [ ] All functions have `# TODO(AUTH):` comments for real implementation
- [ ] Unit tests pass (5 scenarios)
- [ ] Integration tests pass (2 scenarios)
- [ ] `.env.example` updated with auth configuration
- [ ] CRITICAL warning logged when mock mode enabled in non-dev environments
- [ ] API docs show UserContext in dependency listings
- [ ] Code reviewed with explicit sign-off on TODO marker coverage
- [ ] Demo: any existing route can receive UserContext via Depends

---

## 8. Tasks & Sub-Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| PR01-T1 | Create `app/models/user_context.py` with `UserRole` enum and `UserContext` Pydantic model | Backend | 1h | — |
| PR01-T2 | Create `app/services/ai/mock_auth.py` with `_extract_user_context_from_headers()` and `get_current_user()` | Backend | 2h | PR01-T1 |
| PR01-T3 | Create `app/dependencies/auth_dependencies.py` re-exporting `get_current_user` | Backend | 0.5h | PR01-T2 |
| PR01-T4 | Add `AUTH_MOCK_MODE` env var support with startup validation and non-dev warning | Backend | 1h | PR01-T2 |
| PR01-T5 | Write 5 unit tests for `mock_auth.py` | Backend | 1.5h | PR01-T2 |
| PR01-T6 | Write 2 integration tests for auth dependency injection | Backend | 1h | PR01-T3 |
| PR01-T7 | Update `.env.example` with auth configuration section and TODO comments | Backend | 0.5h | PR01-T4 |
| PR01-T8 | Verify existing routes can use `Depends(get_current_user)` without breaking | Backend | 0.5h | PR01-T3 |
| PR01-T9 | Code review: verify all TODO(AUTH) markers cover real auth requirements | Backend Lead | 1h | PR01-T5, PR01-T6 |

---

---

# US-AI-PR02 — Mock Authorization Service

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 2
**Sprint:** 0 (Foundation)
**Depends On:** US-AI-PR01
**Unlocks:** ALL AI stories that enforce permissions

---

## 1. Functional Specification

### 1.1 User Story

As a **Backend Engineer building AI features**, I want a mock authorization service that validates whether a user can access a course, modify a page, or perform administrative actions, so that AI session scoping, proposal gating, and audit controls can be developed without waiting for the real RBAC system.

### 1.2 Functional Requirements

**FR-1: Course Access Check**
Given a `UserContext` and `course_id`, the service MUST return `True` (authorized). In mock mode, ALL users have access to ALL courses. With `# TODO(AUTHZ):` markers for real course-level RBAC.

**FR-2: Page Access Check**
Given a `UserContext` and `page_id`, the service MUST return `True` (authorized). `# TODO(AUTHZ):` markers for real page-level permissions.

**FR-3: Operation Authorization**
Given a `UserContext`, `operation` (create/update/delete/export), and `resource_type` (course/page/component), return authorization decision including whether auto-apply is allowed.

**FR-4: Role-Gated Admin Operations**
`require_admin()` FastAPI dependency that passes for `ADMIN` role users. `# TODO(AUTHZ):` for real admin permission checks.

**FR-5: Configurable Mock Mode**
`AUTHZ_MOCK_MODE=enabled|disabled` environment variable. When disabled, returns clear error.

**FR-6: Authorization Decision Object**
Return `AuthorizationDecision` Pydantic model with: `allowed: bool`, `reason: str`, `requires_confirmation: bool`, `auto_apply_allowed: bool`.

### 1.3 User Flow

1. AI session middleware calls `authorization_service.can_access_course(user_context, course_id)`
2. Mock service returns `AuthorizationDecision(allowed=True, reason="Mock: all access granted", requires_confirmation=True, auto_apply_allowed=False)`
3. In production (TODO): service checks user's organization membership, course enrollment, and role permissions

---

## 2. Technical Specification

### 2.1 `app/models/authorization.py`

```python
from pydantic import BaseModel, Field

class AuthorizationDecision(BaseModel):
    """Result of an authorization check.

    TODO(AUTHZ): In production, this will be returned by the policy engine
    (OPA/Cedar) based on user roles, resource ownership, and tenant policies.
    """
    allowed: bool = Field(description="Whether the operation is permitted")
    reason: str = Field(description="Human-readable explanation")
    requires_confirmation: bool = Field(
        default=True,
        description="Whether destructive/high-risk operations need explicit user confirmation"
    )
    auto_apply_allowed: bool = Field(
        default=False,
        description="Whether the proposal can be auto-applied without user review"
    )
```

### 2.2 `app/services/ai/mock_authorization.py`

```python
"""
Mock Authorization Service

TODO(AUTHZ): Replace with real RBAC / policy engine (OPA/Cedar).
All mock methods return ALLOWED for everything. Real implementation will:
1. Check user's organization membership
2. Verify course-level permissions (owner, editor, viewer)
3. Enforce role-based operation restrictions
4. Evaluate policy rules for auto-apply decisions
5. Log authorization decisions for audit
"""

import os
from app.models.user_context import UserContext
from app.models.authorization import AuthorizationDecision

_AUTHZ_MOCK_MODE = os.getenv("AUTHZ_MOCK_MODE", "enabled").lower() in ("enabled", "1", "true", "yes")


async def can_access_course(user: UserContext, course_id: str) -> AuthorizationDecision:
    """Check if user can access a course.

    TODO(AUTHZ): Implement real check:
    1. Query organization membership for user
    2. Verify course belongs to user's organization
    3. Check user's role has course access permission
    """
    if not _AUTHZ_MOCK_MODE:
        raise HTTPException(status_code=501, detail="Real authorization not yet implemented")
    return AuthorizationDecision(
        allowed=True,
        reason=f"Mock: user {user.user_id} granted access to course {course_id}",
        requires_confirmation=True,
        auto_apply_allowed=False,
    )


async def can_modify_page(user: UserContext, page_id: str, operation: str) -> AuthorizationDecision:
    """Check if user can modify a page.

    TODO(AUTHZ): Implement real check:
    1. Resolve page's parent course
    2. Delegate to can_access_course
    3. Check page-level edit lock
    4. Validate operation type against user role
    """
    if not _AUTHZ_MOCK_MODE:
        raise HTTPException(status_code=501, detail="Real authorization not yet implemented")
    return AuthorizationDecision(
        allowed=True,
        reason=f"Mock: user {user.user_id} granted {operation} on page {page_id}",
        requires_confirmation=(operation == "delete"),
        auto_apply_allowed=(operation == "update"),
    )


async def require_admin(user: UserContext):
    """FastAPI dependency: require admin role.

    TODO(AUTHZ): Replace with real admin permission check against
    organization-scoped admin roles.
    """
    if not _AUTHZ_MOCK_MODE:
        raise HTTPException(status_code=501, detail="Real authorization not yet implemented")
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
```

---

## 6. Validation & Testing

- TC-PR02-01: `can_access_course()` returns allowed=True for any course_id
- TC-PR02-02: `can_modify_page()` returns requires_confirmation=True for delete operations
- TC-PR02-03: `can_modify_page()` returns auto_apply_allowed=True for update operations
- TC-PR02-04: `require_admin()` passes for ADMIN role, raises 403 for INSTRUCTOR
- TC-PR02-05: `AUTHZ_MOCK_MODE=disabled` raises 501 for all methods

---

## 7. Definition of Done

- [ ] `AuthorizationDecision` model defined
- [ ] `mock_authorization.py` implemented with `can_access_course()`, `can_modify_page()`, `require_admin()`
- [ ] All functions have `# TODO(AUTHZ):` comments
- [ ] `AUTHZ_MOCK_MODE` env var honored
- [ ] Unit tests pass (5 scenarios)
- [ ] Integration test: route with `Depends(require_admin)` rejects non-admin
- [ ] Code reviewed

---

## 8. Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| PR02-T1 | Create `app/models/authorization.py` with `AuthorizationDecision` model | Backend | 0.5h | PR01-T1 |
| PR02-T2 | Create `app/services/ai/mock_authorization.py` with all 3 methods | Backend | 1.5h | PR02-T1 |
| PR02-T3 | Add `AUTHZ_MOCK_MODE` env var | Backend | 0.5h | PR02-T2 |
| PR02-T4 | Write 5 unit tests | Backend | 1h | PR02-T2 |
| PR02-T5 | Write integration test for require_admin dependency | Backend | 0.5h | PR02-T2 |
| PR02-T6 | Code review | Lead | 0.5h | PR02-T4 |

---

---

# US-AI-PR03 — Mock Multi-Tenancy Context

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 2
**Sprint:** 0 (Foundation)
**Depends On:** US-AI-PR01
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

# US-AI-PR04 — Mock Session Authentication Middleware

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 3
**Sprint:** 0 (Foundation)
**Depends On:** US-AI-PR01, US-AI-PR02, US-AI-PR03
**Unlocks:** US-AI-006 (AI session creation), US-AI-023 (chat endpoint), all tool-calling stories

---

## 1. Functional Specification

### 1.1 User Story

As a **Backend Engineer building AI features**, I want a mock session authentication middleware that validates the `Authorization: Session {sessionId}` header format and attaches session context to requests, so that AI tool endpoints can enforce session scoping without waiting for a real distributed session store.

### 1.2 Functional Requirements

**FR-1: Session Header Parsing**
The middleware MUST extract `session_id` from `Authorization: Session {sessionId}` headers. Requests without this header on AI routes MUST receive 401.

**FR-2: Session Validation**
Given a `session_id`, the middleware MUST look up the session in an in-memory mock session store and validate it is not expired. Expired sessions receive 440 Session Expired.

**FR-3: Session Context Attachment**
Valid sessions MUST attach a `SessionContext` to `request.state.session` for downstream route handlers.

**FR-4: Course Scope Enforcement**
`validate_session_course_scope(session_id, course_id)` MUST verify the session is scoped to the given course. Cross-course access receives 403.

**FR-5: Mock Session Store**
In-memory dictionary of mock sessions. Sessions expire after `AI_SESSION_TTL_HOURS` (default 24h). `# TODO(SESSION):` markers for Redis-backed store.

**FR-6: Selective Middleware Application**
The middleware MUST only validate sessions on AI routes (`/api/v1/ai/*`). Existing routes (`/api/v1/courses`, etc.) MUST NOT be affected.

---

## 2. Technical Specification

### 2.1 `app/middleware/session_middleware.py`

```python
"""
Session Authentication Middleware

TODO(SESSION): Replace in-memory mock session store with:
1. Redis-backed session store with TTL and auto-expiry
2. Session persistence across server restarts
3. Distributed session validation (multiple API servers)
4. Session activity tracking and idle timeout
5. Session revocation on logout or security events
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

class SessionContext(BaseModel):
    """AI authoring session context.

    TODO(SESSION): Add created_at, last_accessed_at, ip_address, user_agent
    for real session management.
    """
    session_id: str
    user_id: str
    organization_id: str
    course_id: str          # Immutable: cannot change course within a session
    created_at: datetime
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

# TODO(SESSION): Replace with Redis client
_MOCK_SESSION_STORE: Dict[str, SessionContext] = {}

def create_mock_session(user_id: str, org_id: str, course_id: str, ttl_hours: int = 24) -> SessionContext:
    """Create a new session in the mock store.

    TODO(SESSION): Persist to Redis with TTL. Generate cryptographically
    secure session tokens.
    """
    session = SessionContext(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        organization_id=org_id,
        course_id=course_id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
    )
    _MOCK_SESSION_STORE[session.session_id] = session
    return session

def get_mock_session(session_id: str) -> Optional[SessionContext]:
    """Retrieve and validate a session from the mock store.

    TODO(SESSION): Query Redis with TTL check.
    """
    session = _MOCK_SESSION_STORE.get(session_id)
    if session and session.is_expired():
        del _MOCK_SESSION_STORE[session_id]
        return None
    return session

def validate_session_course_scope(session_id: str, course_id: str) -> bool:
    """Verify session is scoped to the given course.

    TODO(SESSION): Add real course ownership validation against DB.
    """
    session = get_mock_session(session_id)
    return session is not None and session.course_id == course_id
```

---

## 6. Validation & Testing

- TC-PR04-01: Request to `/api/v1/ai/sessions` without `Authorization` header returns 401
- TC-PR04-02: Request with valid `Authorization: Session {id}` header passes middleware
- TC-PR04-03: Expired session returns 440 with "Session expired" body
- TC-PR04-04: Session scoped to course-A cannot access course-B (403)
- TC-PR04-05: Existing routes (`/api/v1/courses`) are NOT affected by session middleware
- TC-PR04-06: `create_mock_session()` returns session with 24h expiry

---

## 7. Definition of Done

- [ ] `SessionContext` model defined
- [ ] Session middleware implemented with header parsing and validation
- [ ] In-memory mock session store with expiry working
- [ ] `validate_session_course_scope()` working
- [ ] Middleware only applied to `/api/v1/ai/*` routes
- [ ] All functions have `# TODO(SESSION):` comments
- [ ] Unit tests pass (6 scenarios)
- [ ] Integration test: AI route with valid session, expired session, wrong course
- [ ] Existing route regression: all pre-AI routes still work
- [ ] Code reviewed

---

## 8. Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| PR04-T1 | Create `app/models/session_context.py` with `SessionContext` model | Backend | 0.5h | — |
| PR04-T2 | Create `app/middleware/session_middleware.py` with middleware and mock store | Backend | 2h | PR04-T1 |
| PR04-T3 | Register middleware in `app/main.py` for `/api/v1/ai/*` routes only | Backend | 1h | PR04-T2 |
| PR04-T4 | Write 6 unit tests for session lifecycle and scope enforcement | Backend | 1.5h | PR04-T3 |
| PR04-T5 | Run full existing test suite to verify zero regression on non-AI routes | Backend | 1h | PR04-T3 |
| PR04-T6 | Code review with explicit sign-off on TODO(SESSION) markers | Lead | 0.5h | PR04-T4 |

---

---

# US-AI-PR05 — Mock User & Organization Resolver

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 2
**Sprint:** 0 (Foundation)
**Depends On:** US-AI-PR01, US-AI-PR03
**Unlocks:** ALL AI stories that reference user profiles or organization settings

---

## 1. Functional Specification

### 1.1 User Story

As a **Backend Engineer building AI features**, I want mock resolvers that return user profiles and organization metadata from mock data stores, so that AI features can display user names, validate organization settings, and populate audit log details without real user/org services.

### 1.2 Functional Requirements

**FR-1: User Profile Resolution**
`get_user_profile(user_id)` MUST return a mock `UserProfile` with `display_name`, `email`, `avatar_url`, `role`, and `organization_id`.

**FR-2: Organization Settings Resolution**
`get_organization_settings(org_id)` MUST return mock `OrganizationSettings` with AI feature flags, rate limits, cost caps, and allowed models.

**FR-3: Organization Member List**
`list_organization_members(org_id)` MUST return a list of mock users in the organization. Used for collaboration features (US-AI-047).

**FR-4: Bulk User Resolution**
`resolve_users(user_ids: list[str])` MUST return a dict of `user_id -> UserProfile`. `# TODO(USER):` for real user service batch resolution.

**FR-5: Mock Data Consistency**
Repeated calls with the same `user_id` or `org_id` MUST return consistent mock data (deterministic from the ID).

---

## 2. Technical Specification

### 2.1 `app/services/ai/mock_user_org_resolver.py`

```python
"""
Mock User & Organization Resolver

TODO(USER): Replace with real user service (identity provider / directory).
TODO(TENANT): Replace with real organization service (tenant registry).

Production will integrate with:
- Identity Provider (Auth0, Okta, Azure AD) for user profiles
- Tenant Registry Service for organization settings and billing
- Organization Membership Service for member lists
"""

import hashlib
from typing import Dict, List, Optional
from app.models.user_context import UserContext, UserRole

# Deterministic mock data seeded from UUIDs
def _mock_name(user_id: str) -> str:
    """Generate a deterministic mock display name from a user ID."""
    names = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn", "Avery"]
    idx = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % len(names)
    return f"{names[idx]} (Mock User {user_id[:8]})"


async def get_user_profile(user_id: str) -> dict:
    """Resolve a mock user profile.

    TODO(USER): Call identity provider API: GET /users/{user_id}
    Returns real display_name, email, avatar_url, department, etc.
    """
    return {
        "user_id": user_id,
        "display_name": _mock_name(user_id),
        "email": f"mock.user.{user_id[:8]}@example.com",
        "avatar_url": None,
        "role": "instructor",
        "organization_id": "00000000-0000-0000-0000-000000000100",
    }


async def get_organization_settings(org_id: str) -> dict:
    """Resolve mock organization settings.

    TODO(TENANT): Call tenant registry API: GET /tenants/{org_id}/settings
    Returns real feature flags, rate limits, billing tier, allowed models.
    """
    return {
        "organization_id": org_id,
        "name": f"Mock Organization {org_id[:8]}",
        "ai_authoring_enabled": True,
        "ai_rate_limit_calls_per_hour": 100,
        "ai_rate_limit_calls_per_day": 500,
        "ai_monthly_cost_cap_usd": 500.0,
        "ai_allowed_models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
        "max_courses_per_org": 1000,
        "max_pages_per_course": 100,
        "scorm_export_enabled": True,
    }


async def list_organization_members(org_id: str) -> List[dict]:
    """Return mock organization member list.

    TODO(USER): Query organization membership service.
    Returns real users with roles within the organization.
    """
    return [
        {"user_id": f"user-{i:04d}", "display_name": f"Mock User {i}", "role": "instructor"}
        for i in range(1, 6)
    ]


async def resolve_users(user_ids: List[str]) -> Dict[str, dict]:
    """Batch-resolve user profiles.

    TODO(USER): Batch API call to identity provider.
    """
    result = {}
    for uid in user_ids:
        result[uid] = await get_user_profile(uid)
    return result
```

---

## 6. Validation & Testing

- TC-PR05-01: `get_user_profile()` returns deterministic mock data for a given user_id
- TC-PR05-02: Same user_id returns same display_name on repeated calls
- TC-PR05-03: `get_organization_settings()` returns AI feature flags
- TC-PR05-04: `list_organization_members()` returns 5 mock users
- TC-PR05-05: `resolve_users()` batch resolves 3 user_ids correctly

---

## 7. Definition of Done

- [ ] `mock_user_org_resolver.py` implemented with all 4 functions
- [ ] Deterministic mock data from user_id/org_id seeds
- [ ] All functions have `# TODO(USER):` and `# TODO(TENANT):` comments
- [ ] Unit tests pass (5 scenarios)
- [ ] Integration test: AI session creation uses resolver to populate audit fields
- [ ] Code reviewed

---

## 8. Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| PR05-T1 | Create `app/services/ai/mock_user_org_resolver.py` with all 4 functions | Backend | 1.5h | PR01-T1, PR03-T1 |
| PR05-T2 | Write 5 unit tests for user/org resolution | Backend | 1h | PR05-T1 |
| PR05-T3 | Integration test: resolver used in session creation flow | Backend | 0.5h | PR05-T1 |
| PR05-T4 | Code review | Lead | 0.5h | PR05-T2 |

---

---

# How AI Stories Reference These Prerequisites

Every AI user story (US-AI-001 through US-AI-050) MUST use these dependencies:

```python
# At the top of every AI route file:
from app.dependencies.auth_dependencies import get_current_user
# TODO(AUTH): When real auth is built, this import path won't change

from app.services.ai.mock_authorization import can_access_course, can_modify_page
# TODO(AUTHZ): Replace with real policy engine imports

from app.services.ai.mock_tenancy import get_current_organization, tenant_filter
# TODO(TENANT): Replace with real tenant service imports

from app.middleware.session_middleware import get_mock_session, validate_session_course_scope
# TODO(SESSION): Replace with real session store imports

# Example AI route pattern:
@router.post("/ai/sessions")
async def create_ai_session(
    request: Request,
    course_id: str,
    user: UserContext = Depends(get_current_user),         # PR01
    org: OrganizationContext = Depends(get_current_organization),  # PR03
):
    # Authorization check
    auth = await can_access_course(user, course_id)        # PR02
    if not auth.allowed:
        raise HTTPException(403, detail=auth.reason)

    # Tenant-scoped session creation
    session = create_mock_session(                         # PR04
        user_id=user.user_id,
        org_id=org.organization_id,
        course_id=course_id,
    )

    # Populate audit fields with resolved data
    user_profile = await get_user_profile(user.user_id)    # PR05

    return {"session_id": session.session_id, ...}
```

---

# Updated Epic Dependency Order

| Order | Story | Primary Dependency | Unlocks |
|---|---|---|---|
| **PR1** | **US-AI-PR01 Mock Auth Service** | None | User identity for all stories |
| **PR2** | **US-AI-PR02 Mock AuthZ Service** | PR01 | Permission checks for all stories |
| **PR3** | **US-AI-PR03 Mock Tenancy** | PR01 | Tenant isolation for all stories |
| **PR4** | **US-AI-PR04 Mock Session MW** | PR01, PR02, PR03 | AI session scoping |
| **PR5** | **US-AI-PR05 Mock User/Org Resolver** | PR01, PR03 | User profiles, org settings |
| 1 | US-AI-001 Preserve manual authoring | PR01-PR05 | Safe AI rollout |
| 2 | US-AI-002 AI feature flags and model config | PR01 | Controlled enablement |
| 3 | US-AI-003 Isolated AI API module | US-AI-002 | All AI routes |
| ... | (remaining stories follow original order with PR01-PR05 as implicit deps) | | |
