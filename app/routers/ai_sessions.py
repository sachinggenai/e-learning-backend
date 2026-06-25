"""
AI Sessions Router — US-BKND-AI-006.

Session CRUD endpoints for AI authoring sessions. Each session is scoped
to a user, organization, and course. Sessions are required for all AI
tool-calling and chat operations.

Now fully database-backed (mock bridge removed). Implements:
- Course existence validation via CourseRepository
- Tenant isolation via organization_id scoping
- Max active session limits with configurable cap
- Course state snapshot with live page data
- Ownership validation on GET/DELETE
- Idempotent DELETE (double-close returns 200)
- Audit logging on all lifecycle events

TODOs by story:
    US-BKND-AI-006: COMPLETE — full session lifecycle implemented.
    US-BKND-AI-039: Session context window recovery.

TODO(AUTH): All routes depend on mock auth (US-BKND-AI-PR01). When real auth
is implemented, the Depends(get_current_user) import path won't change.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session as get_db_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.schemas.ai_session import (
    CreateSessionRequest,
    CreateSessionResponse,
    GetSessionResponse,
    DeleteSessionResponse,
)
from app.services.ai.error_envelope import ai_error, AIErrorCode
from app.services.ai.session_service import (
    AISessionService,
    SessionError,
    CourseNotFoundError,
    FeatureDisabledError,
    PermissionDeniedError,
    RateLimitExceededError,
    SessionNotFoundError,
    SessionExpiredError,
    SessionClosedError,
)

router = APIRouter(prefix="/ai", tags=["AI - Sessions"])


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request headers or direct client."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _handle_session_error(err: SessionError):
    """Convert a SessionError into the standardized AI error envelope."""
    return ai_error(
        code=err.code,
        message=err.message,
        status=err.http_status,
        retryable=err.retryable,
    )


@router.post("/sessions", status_code=201)
async def create_session(
    body: CreateSessionRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new AI authoring session scoped to a course.

    Validates:
    - Feature flag AI_AUTHORING_ENABLED is on
    - Course exists in the database
    - User has fewer than AI_MAX_ACTIVE_SESSIONS active sessions
    - Course is accessible (tenant isolation)

    Returns session metadata including a course_state snapshot with
    the current page list, titles, and template types.

    The returned session_id must be included in subsequent AI tool
    and chat requests via the Authorization: Session {sessionId} header.
    """
    try:
        svc = AISessionService(db)
        result = await svc.create_session(
            user_id=user.user_id,
            organization_id=user.organization_id,
            course_id=body.course_id,
            scope=body.scope,
            ip_address=_get_client_ip(request),
        )
        return {
            "status": "ok",
            "session": {
                "sessionId": result["session_id"],
                "userId": result["user_id"],
                "organizationId": result["organization_id"],
                "courseId": result["course_id"],
                "scope": body.scope,
                "status": result["status"],
                "createdAt": result["created_at"].isoformat(),
                "expiresAt": result["expires_at"].isoformat(),
                "courseState": {
                    "courseId": result["course_state"]["course_id"],
                    "title": result["course_state"]["title"],
                    "totalPages": result["course_state"]["total_pages"],
                    "pages": [
                        {
                            "pageId": p["page_id"],
                            "title": p["title"],
                            "templateType": p["template_type"],
                            "order": p["order"],
                            "updatedAt": p.get("updated_at"),
                        }
                        for p in result["course_state"]["pages"]
                    ],
                },
            },
        }
    except FeatureDisabledError as e:
        return _handle_session_error(e)
    except CourseNotFoundError as e:
        return _handle_session_error(e)
    except RateLimitExceededError as e:
        return _handle_session_error(e)
    except SessionError as e:
        return _handle_session_error(e)
    except Exception:
        import logging
        logging.getLogger("ai_authoring").exception(
            "Unexpected error creating session for user=%s course=%s",
            user.user_id[:8], body.course_id[:8],
        )
        return ai_error(
            AIErrorCode.INTERNAL_ERROR,
            "An unexpected error occurred while creating the session.",
        )


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get session metadata and current course state.

    Returns the session info even if expired or closed (status field
    indicates current state). Always builds a fresh course_state
    from the live database (PageRepository).

    Ownership validation: only the session owner can retrieve it.
    Non-existent sessions return 404 (not 403) to prevent enumeration.
    """
    try:
        svc = AISessionService(db)
        result = await svc.get_session(
            session_id=session_id,
            requesting_user_id=user.user_id,
        )
        return {
            "status": "ok",
            "session": {
                "sessionId": result["session_id"],
                "userId": result["user_id"],
                "organizationId": result["organization_id"],
                "courseId": result["course_id"],
                "status": result["status"],
                "createdAt": result["created_at"].isoformat(),
                "expiresAt": result["expires_at"].isoformat(),
                "courseState": {
                    "courseId": result["course_state"]["course_id"],
                    "title": result["course_state"]["title"],
                    "totalPages": result["course_state"]["total_pages"],
                    "pages": [
                        {
                            "pageId": p["page_id"],
                            "title": p["title"],
                            "templateType": p["template_type"],
                            "order": p["order"],
                            "updatedAt": p.get("updated_at"),
                        }
                        for p in result["course_state"]["pages"]
                    ],
                },
            },
        }
    except SessionNotFoundError as e:
        return _handle_session_error(e)
    except PermissionDeniedError as e:
        return _handle_session_error(e)
    except SessionError as e:
        return _handle_session_error(e)
    except Exception:
        import logging
        logging.getLogger("ai_authoring").exception(
            "Unexpected error getting session %s", session_id[:8],
        )
        return ai_error(
            AIErrorCode.INTERNAL_ERROR,
            "An unexpected error occurred while retrieving the session.",
        )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Close (soft-delete) an AI authoring session.

    Idempotent: calling DELETE on an already-closed session returns 200
    with the same response body. After closure, all subsequent tool calls
    with that session_id are rejected.

    Ownership validation: only the session owner can close it.
    """
    try:
        svc = AISessionService(db)
        result = await svc.close_session(
            session_id=session_id,
            requesting_user_id=user.user_id,
        )
        return {
            "status": "ok",
            "session": {
                "sessionId": result["session_id"],
                "status": result["status"],
                "deletedAt": result["deleted_at"].isoformat(),
            },
        }
    except SessionNotFoundError as e:
        return _handle_session_error(e)
    except PermissionDeniedError as e:
        return _handle_session_error(e)
    except SessionError as e:
        return _handle_session_error(e)
    except Exception:
        import logging
        logging.getLogger("ai_authoring").exception(
            "Unexpected error deleting session %s", session_id[:8],
        )
        return ai_error(
            AIErrorCode.INTERNAL_ERROR,
            "An unexpected error occurred while closing the session.",
        )
