"""
AI Tools Router.

Tool-calling endpoints for the AI agent. These endpoints allow the AI
to list pages, fetch page content, propose changes, apply proposals,
confirm destructive operations, and validate data against template contracts.

Implemented:
    US-BKND-AI-005: POST /tools/validate — schema + business rule validation
    US-BKND-AI-007: POST /tools/list_pages — ordered page metadata listing
    US-BKND-AI-007: POST /tools/fetch_page — full page content with components

Stub implementations — full logic will be built in:
    US-BKND-AI-009: Proposal lifecycle
    US-BKND-AI-010: Apply proposals with idempotency
    US-BKND-AI-011: Propose/apply AI-created pages
    US-BKND-AI-012: Propose/apply AI updates to pages
    US-BKND-AI-013: Propose/confirm destructive deletes
    US-BKND-AI-049: Confirmation token system

TODO(AUTH): All routes depend on mock auth (US-BKND-AI-PR01).
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.services.ai.error_envelope import ai_error, AIErrorCode
from app.services.ai.template_contracts import AITemplateContractsService
from app.services.ai.validation_engine import TemplateValidationEngine
from app.services.ai.tool_executor import ToolExecutor, ToolError
from app.services.validation.unified_validator import (
    UnifiedValidator,
    ValidationScope,
)
from app.repositories.ai_session_repo import AISessionRepository

logger = logging.getLogger("ai_authoring")

router = APIRouter(prefix="/ai", tags=["AI - Tools"])


# ── Helper ────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    """Extract client IP from request headers or direct client."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _tool_error_to_response(err: ToolError):
    """Convert a ToolError into the standardized AI error envelope."""
    return ai_error(
        code=err.code,
        message=err.message,
        status=err.http_status,
        retryable=err.retryable,
        **err.details,
    )


# ── Request models ──────────────────────────────────────────────

class ListPagesRequest(BaseModel):
    """Request body for list_pages tool."""
    session_id: str = Field(..., description="AI session ID",
                            min_length=1, max_length=128)


class FetchPageRequest(BaseModel):
    """Request body for fetch_page tool."""
    session_id: str = Field(..., description="AI session ID",
                            min_length=1, max_length=128)
    page_id: str = Field(..., description="Page ID to fetch",
                         min_length=1, max_length=128)


class ValidateCourseRequest(BaseModel):
    """Request body for validate_course tool."""
    session_id: str = Field(..., description="AI session ID",
                            min_length=1, max_length=128)
    validation_scope: str = Field(
        default="full",
        description="Scope: 'schema_only', 'business_rules', 'accessibility', or 'full'"
    )


class ValidateRequest(BaseModel):
    """Request body for the standalone validate endpoint."""
    session_id: str = Field(..., description="AI session ID")
    template_type: str = Field(..., description="Template type key")
    data: dict = Field(..., description="Template data payload to validate")
    validation_scope: str = Field(
        default="full",
        description="Validation scope: 'schema_only', 'business_rules', or 'full'"
    )


# ── Page listing and fetch (US-BKND-AI-007) ─────────────────────

@router.post("/tools/list_pages")
async def list_pages(
    body: ListPagesRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List all pages in the session's course with metadata.

    Returns ordered page metadata: page_id, title,need template_type, order,
    page_etag (SHA-256 hash for staleness detection), and timestamps.

    FR-3: Each page includes page_etag for staleness detection.
    FR-4: Response includes total_pages count.
    FR-8: Empty course returns {pages: [], total_pages: 0}.
    FR-10: Idempotent read — no side effects.

    Session validation:
    - session_id must be active and non-expired (401/440 otherwise)
    - session.user_id must match authenticated user (403 otherwise)
    """
    try:
        executor = ToolExecutor(db)
        result = await executor.execute(
            tool_name="list_pages",
            payload={"session_id": body.session_id},
            caller_user_id=user.user_id,
            ip_address=_get_client_ip(request),
        )
    except ToolError as e:
        return _tool_error_to_response(e)

    http_status = result.pop("_http_status", 200)
    if http_status >= 400:
        return ai_error(
            code=result["code"],
            message=result["message"],
            status=http_status,
            retryable=result.get("retryable", False),
            **result.get("details", {}),
        )

    return {
        "status": "ok",
        "pages": result["data"]["pages"],
        "total_pages": result["data"]["total_pages"],
    }


@router.post("/tools/fetch_page")
async def fetch_page(
    body: FetchPageRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Fetch a single page with full content for AI context.

    Returns complete page data including all components, layout, theme,
    completion config, and page_etag for staleness detection.

    FR-2: Page must belong to the session's course (403 otherwise).
    FR-5: Returns full page record with components array.
    FR-6: Includes page_etag for staleness detection.
    FR-9: Non-existent page returns 404 PAGE_NOT_FOUND.
    FR-10: Idempotent read — no side effects.
    """
    try:
        executor = ToolExecutor(db)
        result = await executor.execute(
            tool_name="fetch_page",
            payload={
                "session_id": body.session_id,
                "page_id": body.page_id,
            },
            caller_user_id=user.user_id,
            ip_address=_get_client_ip(request),
        )
    except ToolError as e:
        return _tool_error_to_response(e)

    http_status = result.pop("_http_status", 200)
    if http_status >= 400:
        return ai_error(
            code=result["code"],
            message=result["message"],
            status=http_status,
            retryable=result.get("retryable", False),
            **result.get("details", {}),
        )

    return {
        "status": "ok",
        "page": result["data"],
    }


# ── Course validation (US-BKND-AI-008) ──────────────────────────

@router.post("/tools/validate_course")
async def validate_course(
    body: ValidateCourseRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Run unified validation on all pages in a course.

    FR-001: Single unified validation endpoint.
    FR-002: Schema validation per page via TemplateValidationEngine.
    FR-003: Business rule validation per page.
    FR-004: Course-level structural checks (order gaps, duplicates, etc.).
    FR-006: Accessibility heuristic checks (alt-text, titles, instructions).
    FR-008: Categorized output (errors, warnings, info).

    Session validation:
    - session_id must be active and non-expired
    - session.user_id must match authenticated user
    """
    # Validate session
    session_repo = AISessionRepository(db)
    session = await session_repo.get_active(body.session_id)
    if session is None:
        existing = await session_repo.get(body.session_id)
        if existing is not None:
            if existing.is_expired():
                return ai_error("SESSION_EXPIRED",
                    "Session has expired. Please create a new session.", status=440)
            if existing.status == "closed":
                return ai_error("SESSION_CLOSED",
                    "This session has been closed.", status=401)
        return ai_error("SESSION_INVALID",
            "Session not found or invalid.", status=401)

    if session.user_id != user.user_id:
        return ai_error("PERMISSION_DENIED",
            "Session does not belong to the authenticated user.", status=403)

    # Run unified validation
    try:
        scope = ValidationScope(body.validation_scope)
    except ValueError:
        return ai_error("VALIDATION_ERROR",
            f"Invalid validation_scope: '{body.validation_scope}'. "
            f"Valid values: {[s.value for s in ValidationScope]}",
            status=400)

    try:
        validator = UnifiedValidator(db)
        result = await validator.validate_course(
            course_id=session.course_id,
            scope=scope,
        )
    except Exception:
        logger.exception("Unified validation failed for course %s",
                         getattr(session, 'course_id', 'unknown')[:8] if hasattr(session, 'course_id') else 'unknown')
        return ai_error("SERVER_ERROR",
            "An unexpected error occurred during validation.", status=503,
            retryable=True)

    # Return structured result
    return {
        "status": "ok",
        "is_valid": result.is_valid,
        "errors": [m.model_dump() for m in result.errors],
        "warnings": [m.model_dump() for m in result.warnings],
        "info": [m.model_dump() for m in result.info],
        "metadata": result.metadata,
    }


# ═══════════════════════════════════════════════════════════════════
# Page proposal tools (US-BKND-AI-011)
# ═══════════════════════════════════════════════════════════════════

class ProposeCreatePageRequest(BaseModel):
    """Request body for propose_create_page tool."""
    session_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=200)
    template_type: str = Field(..., min_length=1, max_length=64)
    data: dict = Field(default_factory=dict)
    insert_at_index: int = Field(default=-1)


class ProposeUpdatePageRequest(BaseModel):
    """Request body for propose_update_page tool."""
    session_id: str = Field(..., min_length=1, max_length=128)
    page_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(default="", max_length=200)
    data: dict = Field(default_factory=dict)
    base_hash: str = Field(default="", max_length=128,
        description="SHA-256 of current page state for staleness detection")


@router.post("/tools/propose_create_page")
async def propose_create_page(
    body: ProposeCreatePageRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Propose creating a new page. FR1 (US-BKND-AI-011).

    Validates session, template type, schema + business rules.
    Returns proposal_id and validation status. No mutation occurs.
    """
    from app.services.ai.proposal_service import AIProposalService, ProposalError, ProposalNotFoundError
    from app.repositories.ai_session_repo import AISessionRepository

    # Resolve course_id from session
    srepo = AISessionRepository(db)
    session = await srepo.get_active(body.session_id)
    if session is None:
        return ai_error("SESSION_INVALID", "Session not found or expired.", status=401)
    if session.user_id != user.user_id:
        return ai_error("PERMISSION_DENIED", "Session does not belong to user.", status=403)

    try:
        svc = AIProposalService(db)
        result = await svc.create_proposal(
            session_id=body.session_id,
            user_id=user.user_id,
            organization_id=session.organization_id,
            course_id=session.course_id,
            operation="create_page",
            resource_type="page",
            data={
                "title": body.title,
                "template_type": body.template_type,
                "data": body.data,
                "insert_at_index": body.insert_at_index,
            },
        )
    except ProposalError as e:
        return ai_error(code=e.code, message=e.message, status=e.http_status)

    return {
        "status": "ok",
        "proposal_id": result["proposal_id"],
        "validation_status": result["validation_status"],
        "validation_messages": result["validation_messages"],
        "diff": result["diff"],
        "preview": result["preview"],
        "created_at": result["created_at"],
        "expires_at": result["expires_at"],
    }


@router.post("/tools/propose_update_page")
async def propose_update_page(
    body: ProposeUpdatePageRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Propose updating an existing page. FR1 (US-BKND-AI-011).

    Validates session, page ownership, schema + business rules.
    Stores before-state snapshot for optimistic concurrency.
    Returns proposal_id and validation status. No mutation occurs.
    """
    from app.services.ai.proposal_service import AIProposalService, ProposalError
    from app.repositories.ai_session_repo import AISessionRepository

    srepo = AISessionRepository(db)
    session = await srepo.get_active(body.session_id)
    if session is None:
        return ai_error("SESSION_INVALID", "Session not found or expired.", status=401)
    if session.user_id != user.user_id:
        return ai_error("PERMISSION_DENIED", "Session does not belong to user.", status=403)

    try:
        svc = AIProposalService(db)
        result = await svc.create_proposal(
            session_id=body.session_id,
            user_id=user.user_id,
            organization_id=session.organization_id,
            course_id=session.course_id,
            operation="update_page",
            resource_type="page",
            resource_id=body.page_id,
            data={
                "title": body.title,
                "template_type": "",
                "data": body.data,
            },
        )
    except ProposalError as e:
        return ai_error(code=e.code, message=e.message, status=e.http_status)

    return {
        "status": "ok",
        "proposal_id": result["proposal_id"],
        "validation_status": result["validation_status"],
        "validation_messages": result["validation_messages"],
        "diff": result["diff"],
        "preview": result["preview"],
        "created_at": result["created_at"],
        "expires_at": result["expires_at"],
    }


# ═══════════════════════════════════════════════════════════════════
# Proposal apply (US-BKND-AI-009/010)
# ═══════════════════════════════════════════════════════════════════

class ApplyPageProposalRequest(BaseModel):
    """Request body for apply_page_proposal tool."""
    session_id: str = Field(..., min_length=1, max_length=128)
    proposal_id: str = Field(..., min_length=1, max_length=128)
    user_confirmed: bool = Field(default=True)
    idempotency_key: str = Field(default="", max_length=256)


@router.post("/tools/apply_page_proposal")
async def apply_page_proposal(
    body: ApplyPageProposalRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Apply an AI proposal with idempotency, outbox, and post-apply validation.

    US-BKND-AI-010: Idempotent apply via X-Idempotency-Key or idempotency_key field.
    FR-APPLY-001: Transactional mutation + audit + outbox.
    FR-APPLY-002: Idempotency key support for safe retry.
    FR-APPLY-006: Post-apply validation of mutated scope.
    FR-APPLY-008: Outbox event for downstream consumers.
    """
    from app.services.ai.proposal_service import AIProposalService, ProposalError

    try:
        svc = AIProposalService(db)
        result = await svc.apply_with_idempotency(
            proposal_id=body.proposal_id,
            session_id=body.session_id,
            user_id=user.user_id,
            user_confirmed=body.user_confirmed,
            idempotency_key=body.idempotency_key or "",
        )
    except ProposalError as e:
        return ai_error(code=e.code, message=e.message, status=e.http_status)

    return {
        "status": "ok",
        "result": result["result"],
        "applied_at": result.get("applied_at"),
    }


@router.post("/tools/apply_update_proposal")
async def apply_update_proposal(
    body: ApplyPageProposalRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Apply an update proposal with staleness detection (US-BKND-AI-012).

    Enhanced apply for page updates: re-checks base_hash against current
    page state, returns current state on conflict (409 STALE_BASE_HASH),
    and refreshes course state after successful apply.
    """
    from app.services.ai.proposal_service import AIProposalService, ProposalError, ProposalConflictError

    try:
        svc = AIProposalService(db)
        result = await svc.apply_with_idempotency(
            proposal_id=body.proposal_id,
            session_id=body.session_id,
            user_id=user.user_id,
            user_confirmed=body.user_confirmed,
            idempotency_key=body.idempotency_key or "",
        )
    except ProposalConflictError as e:
        # Return current state on conflict
        from app.repositories.ai_proposal_repo import AIProposalRepository
        prepo = AIProposalRepository(db)
        prop = await prepo.get(body.proposal_id)
        current_state = {}
        if prop and prop.target_id:
            from app.repositories.page_component_repo import PageRepository
            prepo2 = PageRepository(db)
            page = await prepo2.get(prop.target_id)
            if page:
                current_state = page.to_dict(include_components=True)
        return ai_error(
            code="STALE_BASE_HASH",
            message="Page has been modified since proposal was created. Please re-fetch and propose again.",
            status=409, retryable=True,
            proposal_base_hash="", current_page=current_state,
        )
    except ProposalError as e:
        return ai_error(code=e.code, message=e.message, status=e.http_status)

    return {
        "status": "ok",
        "result": result["result"],
        "applied_at": result.get("applied_at"),
    }


# ═══════════════════════════════════════════════════════════════════
# Destructive delete with confirmation (US-BKND-AI-013)
# ═══════════════════════════════════════════════════════════════════

class ProposeDeletePageRequest(BaseModel):
    """Request body for propose_delete_page tool."""
    session_id: str = Field(..., min_length=1, max_length=128)
    page_id: str = Field(..., min_length=1, max_length=128)


class ConfirmDeletePageRequest(BaseModel):
    """Request body for confirm_delete_page tool."""
    session_id: str = Field(..., min_length=1, max_length=128)
    proposal_id: str = Field(..., min_length=1, max_length=128)
    confirmation_token: str = Field(..., min_length=1, max_length=256)


@router.post("/tools/propose_delete_page")
async def propose_delete_page(
    body: ProposeDeletePageRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Propose deleting a page with dependency impact analysis (US-BKND-AI-013).

    Creates a delete proposal with before-state snapshot and confirmation
    token. Returns dependency warnings (branching rules, final assessment)
    but does NOT mutate any data.
    """
    from app.services.ai.proposal_service import AIProposalService, ProposalError
    from app.repositories.ai_session_repo import AISessionRepository
    from app.repositories.ai_confirmation_repo import AIConfirmationTokenRepository
    from app.models.ai_models import AIConfirmationTokenRecord
    from datetime import datetime, timedelta
    import secrets

    srepo = AISessionRepository(db)
    session = await srepo.get_active(body.session_id)
    if session is None:
        return ai_error("SESSION_INVALID", "Session not found or expired.", status=401)
    if session.user_id != user.user_id:
        return ai_error("PERMISSION_DENIED", "Session does not belong to user.", status=403)

    try:
        svc = AIProposalService(db)
        result = await svc.create_proposal(
            session_id=body.session_id,
            user_id=user.user_id,
            organization_id=session.organization_id,
            course_id=session.course_id,
            operation="delete_page",
            resource_type="page",
            resource_id=body.page_id,
            data={"title": "", "template_type": "", "data": {}},
        )
    except ProposalError as e:
        return ai_error(code=e.code, message=e.message, status=e.http_status)

    # Generate confirmation token
    token = secrets.token_hex(32)
    now = datetime.utcnow()
    token_record = AIConfirmationTokenRecord(
        proposal_id=result["proposal_id"],
        session_id=body.session_id,
        user_id=user.user_id,
        action_type="delete_page",
        description=f"Delete page {body.page_id}",
        is_confirmed=False,
        expires_at=now + timedelta(minutes=15),
        created_at=now,
        updated_at=now,
    )
    trepo = AIConfirmationTokenRepository(db)
    await trepo.create(token_record)

    # Basic dependency impact analysis
    warnings = await _analyze_delete_impact(db, body.page_id, session.course_id)

    return {
        "status": "ok",
        "proposal_id": result["proposal_id"],
        "confirmation_token": token,
        "token_expires_at": token_record.expires_at.isoformat(),
        "validation_status": result["validation_status"],
        "diff": result["diff"],
        "dependency_warnings": warnings,
        "preview": result["preview"],
        "created_at": result["created_at"],
        "expires_at": result["expires_at"],
    }


@router.post("/tools/confirm_delete_page")
async def confirm_delete_page(
    body: ConfirmDeletePageRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Confirm and execute a page delete (US-BKND-AI-013).

    Validates the confirmation token (exists, not expired, not used),
    then executes the deletion via the proposal apply flow.
    """
    from app.services.ai.proposal_service import AIProposalService, ProposalError
    from app.repositories.ai_confirmation_repo import AIConfirmationTokenRepository
    from app.repositories.ai_session_repo import AISessionRepository

    # Validate session
    srepo = AISessionRepository(db)
    session = await srepo.get_active(body.session_id)
    if session is None:
        return ai_error("SESSION_INVALID", "Session not found or expired.", status=401)

    # Validate confirmation token
    trepo = AIConfirmationTokenRepository(db)
    token_record = await trepo.get_valid(body.confirmation_token)
    if token_record is None:
        return ai_error("CONFIRMATION_TOKEN_INVALID",
            "Confirmation token is invalid or expired. Please request a new delete proposal.",
            status=403)

    # Consume the token (one-time use)
    try:
        await trepo.consume(body.confirmation_token)
    except Exception:
        return ai_error("CONFIRMATION_TOKEN_INVALID",
            "Confirmation token has already been used.", status=403)

    # Execute the apply
    try:
        svc = AIProposalService(db)
        result = await svc.apply_with_idempotency(
            proposal_id=body.proposal_id,
            session_id=body.session_id,
            user_id=user.user_id,
            user_confirmed=True,
        )
    except ProposalError as e:
        return ai_error(code=e.code, message=e.message, status=e.http_status)

    return {
        "status": "ok",
        "result": result["result"],
        "applied_at": result.get("applied_at"),
    }


async def _analyze_delete_impact(
    db: AsyncSession, page_id: str, course_id: str
) -> list:
    """Analyze impact of deleting a page. Returns list of warning dicts."""
    warnings = []

    try:
        # Check if this page is referenced by branching rules
        from app.models.branching import BranchRule
        from sqlalchemy import select
        q = select(BranchRule).where(
            (BranchRule.source_page_id == page_id)
            | (BranchRule.target_page_id == page_id)
        )
        rules = (await db.execute(q)).scalars().all()
        if rules:
            warnings.append({
                "code": "BRANCHING_RULE_REFERENCE",
                "message": f"Deleting this page will affect {len(rules)} branching rule(s).",
                "severity": "warning",
                "rule_ids": [r.rule_id if hasattr(r, 'rule_id') else str(r.id) for r in rules],
            })
    except Exception:
        pass

    try:
        # Check if this is the final assessment page
        from app.repositories.page_component_repo import PageRepository
        prepo = PageRepository(db)
        page = await prepo.get(page_id)
        if page and page.layout and isinstance(page.layout, dict):
            if page.layout.get("templateType") == "final-assessment":
                warnings.append({
                    "code": "FINAL_ASSESSMENT_DELETION",
                    "message": "This page is a final assessment. Deleting it will remove course scoring.",
                    "severity": "warning",
                })
    except Exception:
        pass

    try:
        # Check remaining page count
        from app.repositories.page_component_repo import PageRepository
        prepo = PageRepository(db)
        remaining = await prepo.list_by_course(course_id)
        if len(remaining) <= 1:
            warnings.append({
                "code": "LAST_PAGE_DELETION",
                "message": "This is the only page in the course. Deleting it will leave an empty course.",
                "severity": "warning",
            })
    except Exception:
        pass

    return warnings


# ═══════════════════════════════════════════════════════════════════
# Similar course retrieval (US-BKND-AI-015)
# ═══════════════════════════════════════════════════════════════════

class QuerySimilarCoursesRequest(BaseModel):
    """Request body for query_similar_courses tool."""
    session_id: str = Field(..., min_length=1, max_length=128)
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict] = Field(default=None)


@router.post("/tools/query_similar_courses")
async def query_similar_courses(
    body: QuerySimilarCoursesRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Search for similar courses within the organization (US-BKND-AI-015).

    Uses three-tier retrieval: pgvector → full-text → keyword.
    Results are for style/tone guidance only — never authoritative
    for API contracts or schemas.
    """
    from app.services.ai.similar_course_service import (
        SimilarCourseService,
        FeatureDisabledError,
        SessionValidationError,
    )

    service = SimilarCourseService(db)

    try:
        result = await service.query_similar_courses(
            session_id=body.session_id,
            query=body.query,
            max_results=body.max_results,
            filters=body.filters,
            user_id=user.user_id,
        )
        return {"status": "ok", **result}

    except FeatureDisabledError as exc:
        return ai_error("FEATURE_DISABLED", str(exc), status=404)
    except SessionValidationError as exc:
        return ai_error(exc.code, exc.message, status=exc.http_status)
    except Exception:
        logger.exception("Unexpected error in query_similar_courses")
        return ai_error(
            "SERVER_ERROR",
            "An unexpected error occurred while searching for similar courses.",
            status=503,
        )


# ── Validation endpoint (US-BKND-AI-005) ────────────────────────

@router.post("/tools/validate")
async def validate_template_data(
    body: ValidateRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Validate template data against schema and business rules (FR-4).

    This standalone validation endpoint allows the AI agent to check
    whether its proposed data is valid BEFORE creating a proposal.
    It runs both JSON Schema validation and per-template-type business
    rule checks.

    Returns a ValidationResult with status (valid/warning/error),
    structured messages with error codes, and the schema signature.
    """
    contracts = AITemplateContractsService(db)
    engine = TemplateValidationEngine(contracts)

    result = await engine.validate(
        template_type=body.template_type,
        data=body.data,
        scope=body.validation_scope,  # type: ignore
    )

    return {
        "status": result.status,
        "schema_status": result.schema_status,
        "business_rules_status": result.business_rules_status,
        "validation_messages": [
            {
                "severity": msg.severity,
                "code": msg.code,
                "field": msg.field,
                "message": msg.message,
                "hint": msg.hint,
                "min": msg.min,
                "max": msg.max,
                "actual": msg.actual,
            }
            for msg in result.messages
        ],
        "schema_signature": result.schema_signature,
        "template_version": result.template_version,
    }
