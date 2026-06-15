"""
User context model for AI authoring authentication.

TODO(AUTH): When real authentication is implemented, extend this model
with JWT claims, token expiry, refresh token, and MFA status.
The UserContext will be populated from validated JWT claims rather than
bare HTTP headers.

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR01_enriched.md
"""

from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """User roles for authorization decisions.

    TODO(AUTH): When real RBAC is implemented, roles will be loaded from
    the identity provider's claims or the organization membership service.
    """
    INSTRUCTOR = "instructor"    # Can author courses and use AI features
    REVIEWER = "reviewer"         # Can review and validate content
    ADMIN = "admin"               # Can manage tenants, audit, configure
    LEARNER = "learner"           # Read-only access to published courses


class UserContext(BaseModel):
    """Identity context extracted from the current request.

    In mock mode, this is populated from HTTP headers (X-User-ID,
    X-Organization-ID, X-User-Role, X-User-Email).

    TODO(AUTH): In production, this will be populated from JWT claims
    or session tokens, not from bare HTTP headers. The JWT will contain
    user_id, org_id, role, and email as claims. Token signature will be
    verified against the auth provider's public key.
    """

    user_id: str = Field(
        default="00000000-0000-0000-0000-000000000001",
        description="UUID of the authenticated user",
    )
    organization_id: str = Field(
        default="00000000-0000-0000-0000-000000000100",
        description="UUID of the user's active organization/tenant",
    )
    role: UserRole = Field(
        default=UserRole.INSTRUCTOR,
        description="User's role within the organization",
    )
    email: str = Field(
        default="mock.instructor@example.com",
        description="User's email address (used for audit log attribution)",
    )
    is_authenticated: bool = Field(
        default=True,
        description="Whether the user passed authentication",
    )

    @property
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN

    @property
    def can_author(self) -> bool:
        """Check if user can author courses (instructor or admin)."""
        return self.role in (UserRole.INSTRUCTOR, UserRole.ADMIN)

    class Config:
        # NOTE: use_enum_values is intentionally False so that
        # user.role returns UserRole enum (not str), enabling
        # user.role == UserRole.ADMIN and user.role.value comparisons.
        use_enum_values = False
