# US-BKND-AI-PR02 — Mock Authorization Service

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 2
**Sprint:** 0 (Foundation)
**Depends On:** US-BKND-AI-PR01
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