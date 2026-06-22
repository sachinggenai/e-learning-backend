"""AI Proposal Lifecycle Router — US-BKND-AI-009.

Endpoints:
  POST   /api/v1/ai/proposals              — Create proposal
  GET    /api/v1/ai/proposals              — List proposals
  GET    /api/v1/ai/proposals/{id}         — Get proposal detail
  POST   /api/v1/ai/proposals/{id}/apply   — Apply proposal
  POST   /api/v1/ai/proposals/{id}/cancel  — Cancel proposal
"""

import logging
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.services.ai.error_envelope import ai_error, AIErrorCode
from app.services.ai.proposal_service import (
    AIProposalService, ProposalError, ProposalNotFoundError,
    ProposalStaleError, ProposalConflictError,
)
from app.repositories.ai_session_repo import AISessionRepository

logger = logging.getLogger("ai_authoring")
router = APIRouter(prefix="/ai", tags=["AI - Proposals"])


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _handle_proposal_err(err: ProposalError):
    return ai_error(code=err.code, message=err.message, status=err.http_status)


# ── Request Schemas ────────────────────────────────────────────

class CreateProposalRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    operation: str = Field(..., pattern=r"^(create_page|update_page|delete_page)$")
    resource_type: str = Field(default="page", pattern=r"^(page|course)$")
    resource_id: Optional[str] = Field(default=None, max_length=128)
    data: dict = Field(default_factory=dict)


class ApplyProposalRequest(BaseModel):
    user_confirmed: bool = Field(default=True)


class CancelProposalRequest(BaseModel):
    reason: str = Field(default="")


# ── US-BKND-AI-013: Delete Page Proposal Schemas ──────────────

class ProposeDeletePageRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    page_id: str = Field(..., min_length=1, max_length=128)


class ConfirmDeletePageRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    proposal_id: str = Field(..., min_length=1, max_length=128)
    user_approved_delete: bool = Field(
        default=False,
        description="Must be true to confirm destructive deletion",
    )
    confirmation_token: str = Field(
        default="",
        min_length=64,
        max_length=64,
        description="The confirmation token from the propose response",
    )


# ── Endpoints ──────────────────────────────────────────────────

@router.post("/proposals", status_code=201)
async def create_proposal(
    body: CreateProposalRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create a new AI proposal. FR001-FR003."""
    try:
        svc = AIProposalService(db)
        result = await svc.create_proposal(
            session_id=body.session_id, user_id=user.user_id,
            organization_id=user.organization_id,
            course_id="",  # resolved from session internally
            operation=body.operation, resource_type=body.resource_type,
            data=body.data, resource_id=body.resource_id,
        )
    except ProposalError as e:
        return _handle_proposal_err(e)

    return {"status": "ok", "proposal": result}


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get full proposal detail."""
    try:
        svc = AIProposalService(db)
        result = await svc.get_proposal(proposal_id)
    except ProposalNotFoundError as e:
        return _handle_proposal_err(e)
    return {"status": "ok", "proposal": result}


@router.post("/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: str,
    body: ApplyProposalRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Apply a pending proposal. FR004."""
    try:
        svc = AIProposalService(db)
        result = await svc.apply_proposal(
            proposal_id=proposal_id, session_id="", user_id=user.user_id,
            user_confirmed=body.user_confirmed,
        )
    except ProposalError as e:
        return _handle_proposal_err(e)
    return {"status": "ok", "proposal": result}


@router.post("/proposals/{proposal_id}/cancel")
async def cancel_proposal(
    proposal_id: str,
    body: CancelProposalRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Cancel a pending proposal. FR005."""
    try:
        svc = AIProposalService(db)
        result = await svc.cancel_proposal(
            proposal_id=proposal_id, session_id="", user_id=user.user_id,
            reason=body.reason,
        )
    except ProposalError as e:
        return _handle_proposal_err(e)
    return {"status": "ok", "proposal": result}


@router.get("/proposals")
async def list_proposals(
    course_id: Optional[str] = None,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List proposals with filters and pagination. FR009."""
    svc = AIProposalService(db)
    result = await svc.list_proposals(
        course_id=course_id, session_id=session_id,
        status=status, page=page, page_size=page_size,
    )
    return {"status": "ok", **result}


# ── US-BKND-AI-013: Delete Page Proposal Endpoints ────────────

@router.post("/proposals/delete-page", status_code=201)
async def propose_delete_page(
    body: ProposeDeletePageRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Propose deletion of a page with dependency analysis and confirmation token.

    US-BKND-AI-013 Phase 1: Creates a delete proposal. Never mutates domain data.
    Returns confirmation token, warnings, and page metadata.
    """
    try:
        svc = AIProposalService(db)
        result = await svc.propose_delete_page(
            session_id=body.session_id,
            user_id=user.user_id,
            organization_id=user.organization_id,
            course_id="",  # resolved from session
            page_id=body.page_id,
        )
    except ProposalError as e:
        return _handle_proposal_err(e)

    if result.get("status") == "duplicate":
        return ai_error(
            code="DUPLICATE_PROPOSAL",
            message=result["message"],
            status=409,
            existing_proposal_id=result["proposal_id"],
            existing_proposal_status=result["existing_status"],
        )

    return {"status": "ok", "proposal": result}


@router.post("/proposals/confirm-delete")
async def confirm_delete_page(
    body: ConfirmDeletePageRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Confirm and execute a previously proposed page deletion.

    US-BKND-AI-013 Phase 3: Validates token, checks staleness,
    executes the deletion transactionally.
    """
    try:
        svc = AIProposalService(db)
        result = await svc.confirm_delete_page(
            session_id=body.session_id,
            proposal_id=body.proposal_id,
            user_id=user.user_id,
            course_id="",  # resolved from session
            user_approved_delete=body.user_approved_delete,
            confirmation_token=body.confirmation_token,
        )
    except ProposalError as e:
        return _handle_proposal_err(e)

    return {"status": "ok", "result": result}
