# US-BKND-AI-PR01 — Mock Authentication Service

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 3
**Sprint:** 0 (Foundation)
**Depends On:** None
**Unlocks:** US-BKND-AI-PR02, US-BKND-AI-PR04, ALL AI stories

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