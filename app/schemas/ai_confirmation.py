"""Pydantic schemas for the Confirmation Token System.

US-BKND-AI-049: Defines the shape of token-related data in API requests
and responses for destructive operation confirmation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator


# ── Token Generation (Internal, not exposed via API directly) ──────────────


class TokenGenerationRequest(BaseModel):
    """Input for ConfirmationTokenService.generate_token()."""

    session_id: str = Field(..., min_length=1, description="Active AI session ID")
    proposal_id: str = Field(..., min_length=1, description="Proposal ID")
    target_resource_type: Literal["page", "course", "batch", "asset", "config"] = Field(
        ..., description="Type of resource being acted upon"
    )
    target_resource_id: str = Field(..., min_length=1, description="Resource ID")
    operation_type: str = Field(
        ..., min_length=1, description="e.g., delete_page, delete_course"
    )
    resource_hash: str = Field(
        ..., min_length=1, description="Deterministic hash of resource state"
    )
    ttl_minutes: Optional[int] = Field(
        None, ge=1, le=1440, description="Override TTL in minutes (1-1440)"
    )


class TokenGenerationResult(BaseModel):
    """Output from ConfirmationTokenService.generate_token()."""

    token: str = Field(..., description="Plaintext confirmation token (64 hex chars)")
    token_hash: str = Field(
        ..., description="SHA-256 of scope-bound token, for persistence"
    )
    expires_at: datetime = Field(..., description="Token expiry datetime (UTC)")


# ── Token Validation ──────────────────────────────────────────────────────


class TokenValidationRequest(BaseModel):
    """Input for token validation (embedded in confirm-* requests)."""

    confirmation_token: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="The confirmation token received from the propose step",
    )
    user_approved: bool = Field(
        default=True,
        description="Whether the user explicitly approved the operation",
    )

    @field_validator("confirmation_token")
    @classmethod
    def validate_token_hex(cls, v: str) -> str:
        """Ensure the token is valid hex."""
        try:
            bytes.fromhex(v)
        except ValueError as exc:
            raise ValueError(
                "confirmation_token must be a valid 64-character hex string"
            ) from exc
        return v.lower()


class AdminOverrideRequest(BaseModel):
    """Input for admin bypass of confirmation token."""

    confirmation_token: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description="Optional: admin may provide the token for audit trail",
    )
    admin_override: bool = Field(
        default=False,
        description="Set to true to bypass token validation",
    )
    admin_override_reason: str = Field(
        ...,
        min_length=20,
        max_length=1000,
        description="Reason for the override (min 20 characters, recorded in audit)",
    )


# ── Confirmation Response ────────────────────────────────────────────────


class ConfirmationResponse(BaseModel):
    """Generic response for a confirmation operation."""

    status: str = Field(..., description="Operation status: confirmed, token_validated")
    proposal_id: str = Field(..., description="Proposal ID that was confirmed")
    operation: str = Field(..., description="Operation type that was confirmed")
    target_resource_type: Optional[str] = Field(
        None, description="Type of the target resource"
    )
    target_resource_id: Optional[str] = Field(
        None, description="ID of the target resource"
    )
    message: Optional[str] = Field(None, description="Human-readable result message")
    executed_at: Optional[datetime] = Field(
        None, description="When the operation was executed (UTC)"
    )


# ── Security Event Data ───────────────────────────────────────────────────


class SecurityEventData(BaseModel):
    """Structured data for security event logging."""

    event_type: Literal[
        "CONFIRMATION_TOKEN_MISMATCH",
        "CONFIRMATION_ADMIN_OVERRIDE",
        "CONFIRMATION_EXPIRED_ATTEMPT",
        "CONFIRMATION_RESOURCE_CHANGED",
    ] = Field(..., description="Type of security event")
    proposal_id: str = Field(..., description="Proposal ID involved")
    session_id: str = Field(..., description="Session ID involved")
    user_id: Optional[str] = Field(None, description="User ID of the actor")
    ip_address: Optional[str] = Field(None, description="Client IP address")
    details: dict = Field(
        default_factory=dict, description="Additional event-specific details"
    )
    occurred_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the security event occurred (UTC)",
    )
