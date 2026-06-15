"""
Mock Authentication Service.

Provides a FastAPI dependency (`get_current_user`) that extracts user identity
from HTTP headers in development/demo mode.

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

Search for all TODO(AUTH) markers across the codebase to find every
location that needs updating when real auth is implemented.

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR01_enriched.md
"""

import os
import logging
from typing import Optional

from fastapi import Request, HTTPException, Depends

from app.models.user_context import UserContext, UserRole

logger = logging.getLogger("ai_authoring")

# TODO(AUTH): Move to app/core/config.py when real config system is built
_MOCK_MODE = os.getenv("AUTH_MOCK_MODE", "enabled").lower() in (
    "enabled", "1", "true", "yes"
)

# TODO(AUTH): Replace with JWT public key / JWKS endpoint URL
_JWT_SECRET_PLACEHOLDER = "TODO_AUTH_REPLACE_WITH_REAL_JWT_SECRET"

# Warn if mock mode is enabled in non-development environments
_ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
if _MOCK_MODE and _ENVIRONMENT in ("staging", "production"):
    logger.critical(
        "AUTH_MOCK_MODE is ENABLED in %s environment! "
        "This MUST be disabled before production deployment. "
        "Set AUTH_MOCK_MODE=disabled in production.",
        _ENVIRONMENT,
    )


def _extract_user_context_from_headers(request: Request) -> UserContext:
    """Extract user identity from HTTP headers.

    Reads X-User-ID, X-Organization-ID, X-User-Role, and X-User-Email
    headers. Falls back to sensible defaults for missing headers.

    TODO(AUTH): Replace this entire function with JWT Bearer token
    validation. The JWT will contain user_id, org_id, role, and email
    as claims. Token signature will be verified against the auth
    provider's public key.
    """
    user_id = request.headers.get(
        "X-User-ID", "00000000-0000-0000-0000-000000000001"
    ) or "00000000-0000-0000-0000-000000000001"
    org_id = request.headers.get(
        "X-Organization-ID", "00000000-0000-0000-0000-000000000100"
    ) or "00000000-0000-0000-0000-000000000100"
    role_str = request.headers.get("X-User-Role", "instructor") or "instructor"
    email = request.headers.get(
        "X-User-Email", "mock.instructor@example.com"
    ) or "mock.instructor@example.com"

    # Parse role, defaulting to INSTRUCTOR for unrecognized or None values
    try:
        role = UserRole(role_str.lower())
    except (ValueError, AttributeError):
        logger.warning(
            "Unrecognized or missing role '%s' in X-User-Role header, defaulting to instructor",
            role_str,
        )
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

    Usage in route handlers:
        @router.get("/courses")
        async def list_courses(user: UserContext = Depends(get_current_user)):
            # user.user_id, user.organization_id, user.role are available
            ...

    In mock mode: extracts identity from HTTP headers.
    In production (TODO): validates JWT Bearer token and returns claims.

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
            detail=(
                "Real authentication not yet implemented. "
                "Set AUTH_MOCK_MODE=enabled to use mock auth, or "
                "implement the auth service at app/services/auth/."
            ),
        )

    user_context = _extract_user_context_from_headers(request)

    # Attach to request state for downstream middleware and audit logging
    # TODO(AUTH): This will be done by the auth middleware, not here
    request.state.user_context = user_context

    return user_context


# TODO(AUTH): Add these real auth dependencies when auth system is built:
#
# async def get_current_active_user(
#     user: UserContext = Depends(get_current_user),
# ) -> UserContext:
#     """Require an authenticated, non-disabled, non-locked-out user."""
#     # TODO: Check user account status in identity provider
#     return user
#
# async def get_current_admin(
#     user: UserContext = Depends(get_current_user),
# ) -> UserContext:
#     """Require admin role. Raises 403 if not admin."""
#     if user.role != UserRole.ADMIN:
#         raise HTTPException(status_code=403, detail="Admin role required")
#     return user
