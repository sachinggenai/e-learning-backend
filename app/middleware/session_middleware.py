"""Session Authentication Middleware for AI routes.

Validates the Authorization: Session {sessionId} header on AI endpoints.
Uses an in-memory cache for fast validation with database fallback.

Updated for US-BKND-AI-006: Added DB fallback when in-memory cache misses.
The session is first looked up in the in-memory cache; if not found, the
middleware queries the database via AISessionRepository.

TODO(SESSION): Replace in-memory mock session store with:
1. Redis-backed session store with TTL and auto-expiry
2. Session persistence across server restarts
3. Distributed session validation (multiple API servers)
4. Session activity tracking and idle timeout
5. Session revocation on logout or security events

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR04_enriched.md
"""

import asyncio
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.session_context import SessionContext

logger = logging.getLogger("ai_authoring")

# TODO(SESSION): Replace with Redis client
# In production, use Redis with:
# - SETEX session:{session_id} {ttl_seconds} {serialized_session}
# - GET session:{session_id}
# - DEL session:{session_id}
_MOCK_SESSION_STORE: Dict[str, SessionContext] = {}

# Session TTL configuration
# TODO(SESSION): Make this configurable via env var AI_SESSION_TTL_HOURS
_DEFAULT_SESSION_TTL_HOURS = 24

# Routes that require session authentication
_AI_ROUTE_PREFIX = "/api/v1/ai"


def create_mock_session(
    user_id: str,
    org_id: str,
    course_id: str,
    ttl_hours: int = _DEFAULT_SESSION_TTL_HOURS,
    session_id: Optional[str] = None,
) -> SessionContext:
    """Create a new session in the mock store.

    If session_id is provided, uses it; otherwise generates a new UUID.
    Returns a SessionContext with the session_id.

    TODO(SESSION): Persist to Redis with TTL. Generate cryptographically
    secure session tokens instead of UUIDs.
    """
    sid = session_id or str(uuid.uuid4())
    session = SessionContext(
        session_id=sid,
        user_id=user_id,
        organization_id=org_id,
        course_id=course_id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
    )
    _MOCK_SESSION_STORE[sid] = session
    logger.info(
        "Session created in cache: %s for user=%s course=%s org=%s",
        sid[:8],
        user_id[:8],
        course_id[:8],
        org_id[:8],
    )
    return session


def get_mock_session(session_id: str) -> Optional[SessionContext]:
    """Retrieve and validate a session from the mock store.

    Returns None if session not found or expired.
    Auto-cleans expired sessions.

    TODO(SESSION): Query Redis with TTL check.
    """
    session = _MOCK_SESSION_STORE.get(session_id)
    if session is None:
        return None

    if session.is_expired():
        del _MOCK_SESSION_STORE[session_id]
        logger.info("Session %s expired and cleaned up from cache", session_id[:8])
        return None

    return session


def validate_session_course_scope(session_id: str, course_id: str) -> bool:
    """Verify session is scoped to the given course.

    Returns True if session exists, is not expired, and course_id matches.

    TODO(SESSION): Add real course ownership validation against database.
    """
    session = get_mock_session(session_id)
    if session is None:
        return False
    return session.course_id == course_id


def end_mock_session(session_id: str) -> bool:
    """End and remove a session from the mock store.

    Returns True if session was found and removed.

    TODO(SESSION): DEL from Redis.
    """
    if session_id in _MOCK_SESSION_STORE:
        del _MOCK_SESSION_STORE[session_id]
        logger.info("Session %s removed from cache", session_id[:8])
        return True
    return False


async def _lookup_session_in_db(session_id: str) -> Optional[SessionContext]:
    """Fallback: look up a session in the database.

    Used when the in-memory cache misses. On success, the session is
    repopulated into the in-memory cache for future fast lookups.

    Returns None if the session is not found in the DB, is expired,
    or is closed/revoked.
    """
    try:
        from app.db.config import SessionLocal
        from app.repositories.ai_session_repo import AISessionRepository

        async with SessionLocal() as db:
            repo = AISessionRepository(db)
            record = await repo.get_active(session_id)
            if record is None:
                return None

            # Repopulate in-memory cache
            remaining = record.expires_at - datetime.utcnow()
            ttl_hours = max(1, int(remaining.total_seconds() / 3600))
            session = create_mock_session(
                user_id=record.user_id,
                org_id=record.organization_id,
                course_id=record.course_id,
                ttl_hours=ttl_hours,
                session_id=record.session_id,
            )
            logger.info(
                "Session %s recovered from DB into cache", session_id[:8]
            )
            return session
    except Exception:
        logger.exception(
            "DB fallback lookup failed for session %s", session_id[:8]
        )
        return None


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that validates session tokens on AI routes.

    Only applied to routes under /api/v1/ai/*.
    Existing routes are NOT affected.

    Lookup order:
    1. In-memory cache (fast path)
    2. Database fallback (cold cache / server restart)

    Usage in app/main.py:
        app.add_middleware(SessionAuthMiddleware)
    """

    async def dispatch(self, request: Request, call_next):
        # Only validate AI routes
        if not request.url.path.startswith(_AI_ROUTE_PREFIX):
            return await call_next(request)

        # Skip session creation endpoint (it creates sessions, doesn't require one)
        if request.url.path == f"{_AI_ROUTE_PREFIX}/sessions" and request.method == "POST":
            return await call_next(request)

        # Skip feature-status endpoint (no session needed)
        if request.url.path == f"{_AI_ROUTE_PREFIX}/feature-status":
            return await call_next(request)

        # Skip template/config endpoints that don't require sessions
        if request.url.path.startswith(f"{_AI_ROUTE_PREFIX}/templates"):
            return await call_next(request)
        if request.url.path.startswith(f"{_AI_ROUTE_PREFIX}/config"):
            return await call_next(request)

        # Extract session ID from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Session "):
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid Authorization header. "
                       "Expected: 'Authorization: Session {sessionId}'",
            )

        session_id = auth_header.replace("Session ", "", 1).strip()
        if not session_id:
            raise HTTPException(
                status_code=401,
                detail="Empty session ID in Authorization header",
            )

        # Validate session — check cache first, then DB
        session = get_mock_session(session_id)
        if session is None:
            # Fall back to database lookup
            session = await _lookup_session_in_db(session_id)

        if session is None:
            raise HTTPException(
                status_code=440,  # Login Timeout (non-standard but expressive)
                detail="Session invalid or expired. Please create a new session.",
            )

        # Attach session to request state for downstream handlers
        request.state.session = session

        # Continue to route handler
        return await call_next(request)
