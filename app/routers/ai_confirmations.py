"""Generic Confirmation Router for Destructive/Irreversible Operations.

US-BKND-AI-049: Provides a unified confirmation endpoint that any
operation-specific orchestrator can delegate to, or that can be called
directly with the proposal_id and confirmation_token.

Endpoint:
  POST /api/v1/ai/proposals/{proposal_id}/confirm
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.repositories.ai_proposal_repo import AIProposalRepository
from app.services.ai.confirmation_token_service import (
    ConfirmationTokenService,
    ConfirmationTokenError,
    DESTRUCTIVE_OPERATIONS,
)
from app.services.ai.error_envelope import ai_error, AIErrorCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI - Confirmations"])


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


# ── Request Schemas ──────────────────────────────────────────────────

from pydantic import BaseModel, Field, field_validator


class ConfirmProposalRequest(BaseModel):
    """Request body for POST /api/v1/ai/proposals/{proposal_id}/confirm."""

    confirmation_token: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="The confirmation token received from the propose step",
    )
    user_approved: bool = Field(
        default=True,
        description="Whether the user explicitly approved the destructive operation",
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


class AdminConfirmProposalRequest(BaseModel):
    """Admin override request for bypassing confirmation token."""

    admin_override: bool = Field(
        default=False,
        description="Set to true to bypass token validation as admin",
    )
    admin_override_reason: str = Field(
        default="",
        min_length=20,
        max_length=1000,
        description="Reason for the override (min 20 characters)",
    )
    confirmation_token: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description="Optional: admin may provide the token for audit trail",
    )


# ── Endpoints ────────────────────────────────────────────────────────


@router.post(
    "/proposals/{proposal_id}/confirm",
    summary="Confirm a destructive operation using a confirmation token",
    responses={
        200: {"description": "Token validated; operation can proceed"},
        400: {"description": "User confirmation required or invalid request"},
        403: {"description": "Invalid confirmation token"},
        404: {"description": "Proposal not found"},
        409: {"description": "Resource changed, already applied, or not confirmable"},
        410: {"description": "Confirmation token expired or resource deleted"},
    },
)
async def confirm_proposal(
    proposal_id: str,
    body: ConfirmProposalRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Validate a confirmation token for a destructive proposal.

    This endpoint is the GATE that all destructive operations pass through.
    It validates the token and proposal state, returning 200 if the
    confirmation is legitimate. The caller (operation-specific orchestrator)
    must then execute the actual mutation inside a database transaction.

    This endpoint does NOT execute the operation itself — only validates
    that the confirmation is legitimate.
    """
    # 1. Fetch proposal
    proposal_repo = AIProposalRepository(db)
    proposal = await proposal_repo.get(proposal_id)

    if not proposal:
        return ai_error(
            AIErrorCode.NOT_FOUND,
            f"Proposal '{proposal_id}' not found.",
            status=404,
        )

    if proposal.action_type not in DESTRUCTIVE_OPERATIONS:
        return ai_error(
            code="NON_DESTRUCTIVE_OPERATION",
            message=(
                f"Operation '{proposal.action_type}' does not require "
                "confirmation."
            ),
            status=400,
        )

    # 2. Validate token
    token_service = ConfirmationTokenService()

    is_valid, error_code = await token_service.validate_token(
        proposal=proposal,
        received_token=body.confirmation_token,
        user_approved=body.user_approved,
    )

    if not is_valid:
        # Map error_code to HTTP error
        code, *params = error_code.split(":", 1) if error_code else ("UNKNOWN_ERROR",)
        param_str = params[0] if params else ""

        error_map = {
            "PROPOSAL_NOT_CONFIRMABLE": (
                409, code,
                f"Proposal is in status '{param_str}' and cannot be confirmed. "
                "Only pending proposals are confirmable.",
            ),
            "NON_DESTRUCTIVE_OPERATION": (
                400, code,
                "This operation does not require confirmation.",
            ),
            "USER_CONFIRMATION_REQUIRED": (
                400, code,
                "You must set user_approved=true to confirm this destructive operation.",
            ),
            "INVALID_TOKEN_FORMAT": (
                400, code,
                "The confirmation token format is invalid. Must be 64 hex characters.",
            ),
            "NO_CONFIRMATION_TOKEN_SET": (
                400, code,
                "This proposal has no confirmation token set. It may not require confirmation.",
            ),
            "INVALID_CONFIRMATION_TOKEN": (
                403, code,
                "The provided confirmation token is invalid. This may indicate tampering.",
            ),
            "CONFIRMATION_EXPIRED": (
                410, code,
                f"The confirmation token has expired. Maximum TTL is configurable via "
                f"AI_CONFIRMATION_TOKEN_TTL_MINUTES.",
            ),
            "ADMIN_OVERRIDE_REASON_TOO_SHORT": (
                400, code,
                "Admin override reason must be at least 20 characters.",
            ),
        }

        status, err_code, err_message = error_map.get(
            code, (400, code, "Validation failed.")
        )
        return ai_error(code=err_code, message=err_message, status=status)

    # 3. Return success — caller must now execute the operation
    target_resource_type = token_service._get_target_resource_type(proposal)
    target_resource_id = token_service._get_target_resource_id(proposal)

    return {
        "status": "token_validated",
        "proposal_id": proposal.proposal_id,
        "operation": proposal.action_type,
        "target_resource_type": target_resource_type,
        "target_resource_id": target_resource_id,
        "message": "Confirmation token validated. Proceed with operation execution.",
    }
