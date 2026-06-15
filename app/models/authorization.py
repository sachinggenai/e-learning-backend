"""
Authorization decision model for AI authoring.

TODO(AUTHZ): In production, this will be returned by the policy engine
(OPA/Cedar) based on user roles, resource ownership, and tenant policies.

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR02_enriched.md
"""

from pydantic import BaseModel, Field


class AuthorizationDecision(BaseModel):
    """Result of an authorization check.

    TODO(AUTHZ): When real RBAC is implemented, this model will be
    enriched with policy rule IDs, audit trail references, and
    tenant-specific override information.
    """

    allowed: bool = Field(
        default=True,
        description="Whether the operation is permitted",
    )
    reason: str = Field(
        default="Authorization check passed",
        description="Human-readable explanation of the decision",
    )
    requires_confirmation: bool = Field(
        default=True,
        description=(
            "Whether destructive or high-risk operations require "
            "explicit user confirmation before execution"
        ),
    )
    auto_apply_allowed: bool = Field(
        default=False,
        description=(
            "Whether the proposal can be auto-applied without "
            "requiring manual user review"
        ),
    )
