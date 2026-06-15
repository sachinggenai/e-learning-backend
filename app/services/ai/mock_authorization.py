"""
Mock Authorization Service.

Provides authorization check functions that determine whether a user
can access a course, modify a page, or perform administrative actions.

In mock mode: ALL checks return ALLOWED for everything.
In production (TODO): Real RBAC via policy engine (OPA/Cedar).

TODO(AUTHZ): Replace with real RBAC / policy engine. All mock methods
return ALLOWED for everything. Real implementation will:
1. Check user's organization membership
2. Verify course-level permissions (owner, editor, viewer)
3. Enforce role-based operation restrictions
4. Evaluate policy rules for auto-apply decisions
5. Log authorization decisions for audit

Search for all TODO(AUTHZ) markers across the codebase to find every
location that needs updating when real authorization is implemented.

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR02_enriched.md
"""

import os
import logging
from typing import Optional

from fastapi import HTTPException, Depends, Request

from app.models.user_context import UserContext, UserRole
from app.models.authorization import AuthorizationDecision
from app.dependencies.auth_dependencies import get_current_user

logger = logging.getLogger("ai_authoring")

# TODO(AUTHZ): Move to config when real config system is built
_AUTHZ_MOCK_MODE = os.getenv("AUTHZ_MOCK_MODE", "enabled").lower() in (
    "enabled", "1", "true", "yes"
)

_ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
if _AUTHZ_MOCK_MODE and _ENVIRONMENT in ("staging", "production"):
    logger.critical(
        "AUTHZ_MOCK_MODE is ENABLED in %s environment! "
        "This MUST be disabled before production deployment.",
        _ENVIRONMENT,
    )


async def can_access_course(
    user: UserContext,
    course_id: str,
) -> AuthorizationDecision:
    """Check if a user can access a specific course.

    In mock mode: always returns ALLOWED.
    In production (TODO): checks organization membership, course
    enrollment, and role-based course permissions.

    TODO(AUTHZ): Implement real check:
    1. Query organization membership for user
    2. Verify course belongs to user's organization
    3. Check user's role has course access permission
    4. Apply tenant-specific policy overrides
    """
    if not _AUTHZ_MOCK_MODE:
        raise HTTPException(
            status_code=501,
            detail="Real authorization not yet implemented. "
                   "Set AUTHZ_MOCK_MODE=enabled to use mock authZ.",
        )

    return AuthorizationDecision(
        allowed=True,
        reason=(
            f"Mock: user {user.user_id} granted access to "
            f"course {course_id} (org: {user.organization_id})"
        ),
        requires_confirmation=True,
        auto_apply_allowed=False,
    )


async def can_modify_page(
    user: UserContext,
    page_id: str,
    operation: str,
) -> AuthorizationDecision:
    """Check if a user can modify a specific page.

    In mock mode: always returns ALLOWED.
    Operation types: "create", "update", "delete", "reorder".

    Destructive operations (delete) always require confirmation.
    Non-destructive operations (update, create) allow auto-apply
    in mock mode for INSTRUCTOR and ADMIN roles.

    TODO(AUTHZ): Implement real check:
    1. Resolve page's parent course
    2. Delegate to can_access_course for course-level auth
    3. Check page-level edit lock status
    4. Validate operation type against user role permissions
    5. Apply content-specific policies (e.g., assessment pages
       require REVIEWER role for modifications)
    """
    if not _AUTHZ_MOCK_MODE:
        raise HTTPException(
            status_code=501,
            detail="Real authorization not yet implemented. "
                   "Set AUTHZ_MOCK_MODE=enabled to use mock authZ.",
        )

    is_destructive = (operation == "delete")
    can_auto_apply = (
        not is_destructive
        and user.role in (UserRole.INSTRUCTOR, UserRole.ADMIN)
    )

    return AuthorizationDecision(
        allowed=True,
        reason=(
            f"Mock: user {user.user_id} granted {operation} on "
            f"page {page_id} (org: {user.organization_id})"
        ),
        requires_confirmation=is_destructive,
        auto_apply_allowed=can_auto_apply,
    )


async def can_manage_course(
    user: UserContext,
    course_id: str,
    operation: str,
) -> AuthorizationDecision:
    """Check if a user can perform course-level operations.

    Operations: "create", "delete", "export", "archive".

    Course deletion always requires confirmation and is restricted
    to ADMIN role, even in mock mode (safety-first).

    TODO(AUTHZ): Implement real check with course lifecycle policies.
    """
    if not _AUTHZ_MOCK_MODE:
        raise HTTPException(
            status_code=501,
            detail="Real authorization not yet implemented.",
        )

    is_admin = (user.role == UserRole.ADMIN)
    is_destructive = (operation in ("delete", "archive"))

    # Even in mock mode, course deletion is admin-only for safety
    if is_destructive and not is_admin:
        return AuthorizationDecision(
            allowed=False,
            reason=(
                f"Course {operation} requires ADMIN role. "
                f"User {user.user_id} has role {user.role.value}."
            ),
            requires_confirmation=True,
            auto_apply_allowed=False,
        )

    return AuthorizationDecision(
        allowed=True,
        reason=(
            f"Mock: user {user.user_id} granted {operation} on "
            f"course {course_id}"
        ),
        requires_confirmation=is_destructive,
        auto_apply_allowed=not is_destructive,
    )


async def require_admin(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """FastAPI dependency: require admin role.

    Raises 403 Forbidden if user does not have ADMIN role.

    Usage:
        @router.delete("/courses/{course_id}")
        async def delete_course(
            course_id: str,
            admin: UserContext = Depends(require_admin),
        ):
            ...

    TODO(AUTHZ): Replace with real admin permission check against
    organization-scoped admin roles and policies.
    """
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail=f"Admin role required. User has role: {user.role.value}",
        )
    return user
