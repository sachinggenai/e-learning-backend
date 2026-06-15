"""AI Admin Router — US-BKND-AI-025.

Admin endpoints for AI safety events, audit logs, and operational
visibility. These endpoints require elevated permissions.

Endpoints:
    GET /api/v1/ai/admin/safety-events  — List safety events
    GET /api/v1/ai/admin/safety-events/{event_id} — Get single event
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.repositories.ai_safety_event_repo import AISafetyEventRepository
from app.services.ai.error_envelope import ai_error, AIErrorCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai/admin", tags=["AI - Admin"])


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/safety-events")
async def list_safety_events(
    event_type: Optional[str] = Query(
        None,
        description="Filter by event type (prompt_injection_blocked, pii_detected_and_redacted, etc.)",
    ),
    severity: Optional[str] = Query(
        None,
        description="Filter by severity (low, medium, high, critical)",
    ),
    session_id: Optional[str] = Query(
        None,
        description="Filter by session ID",
    ),
    limit: int = Query(50, ge=1, le=200, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List safety events with optional filters.

    US-BKND-AI-025: Admin-auditable safety event records for compliance
    and security review. Returns the most recent events first.
    """
    repo = AISafetyEventRepository(db)
    events = await repo.list_by_type(
        event_type=event_type,
        severity=severity,
        session_id=session_id,
        user_id=None,  # Admin sees all users
        limit=limit,
        offset=offset,
    )

    total = await repo.count_by_type(
        event_type=event_type,
        severity=severity,
    )

    return {
        "status": "ok",
        "items": [e.to_dict() for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/safety-events/{event_id}")
async def get_safety_event(
    event_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get a single safety event by ID."""
    repo = AISafetyEventRepository(db)
    event = await repo.get(event_id)

    if event is None:
        return ai_error(
            AIErrorCode.NOT_FOUND,
            f"Safety event '{event_id}' not found.",
            status=404,
        )

    return {"status": "ok", "event": event.to_dict()}


@router.get("/safety-stats")
async def safety_stats(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get aggregate safety statistics.

    Returns counts by event type and severity for dashboard display.
    """
    repo = AISafetyEventRepository(db)

    event_types = [
        "prompt_injection_blocked",
        "pii_detected_and_redacted",
        "toxic_output_blocked",
        "blocked_term_detected",
        "rate_limit_exceeded",
        "policy_violation",
    ]
    severities = ["low", "medium", "high", "critical"]

    stats_by_type = {}
    for et in event_types:
        stats_by_type[et] = await repo.count_by_type(event_type=et)

    stats_by_severity = {}
    for sev in severities:
        stats_by_severity[sev] = await repo.count_by_type(severity=sev)

    return {
        "status": "ok",
        "by_event_type": stats_by_type,
        "by_severity": stats_by_severity,
    }


# ── US-BKND-AI-020: Audit Log Endpoints ──────────────────────────

from pydantic import BaseModel as PydanticBaseModel, Field as PydanticField


@router.get("/audit-logs")
async def list_audit_logs(
    user_id: str = "",
    course_id: str = "",
    operation: str = "",
    session_id: str = "",
    outcome: str = "",
    date_from: str = "",
    date_to: str = "",
    search: str = "",
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_session),
):
    """Query AI audit logs with filters and pagination (US-BKND-AI-020)."""
    from app.services.ai.audit_query_service import AuditQueryService

    svc = AuditQueryService()
    result = svc.query(
        user_id=user_id or None,
        course_id=course_id or None,
        operation=operation or None,
        session_id=session_id or None,
        outcome=outcome or None,
        date_from=date_from or None,
        date_to=date_to or None,
        search=search or None,
        page=page,
        page_size=min(page_size, 200),
    )
    return {"status": "ok", **result}


@router.get("/audit-summary")
async def audit_operations_summary(
    days: int = 7,
    db: AsyncSession = Depends(get_session),
):
    """Get operations summary for compliance dashboard (US-BKND-AI-020)."""
    from app.services.ai.audit_query_service import AuditQueryService

    svc = AuditQueryService()
    result = svc.get_operations_summary(days=days)
    return {"status": "ok", **result}


@router.get("/audit-logs/course/{course_id}")
async def course_audit_history(
    course_id: str,
    db: AsyncSession = Depends(get_session),
):
    """Get time-ordered change history for a course (US-BKND-AI-020)."""
    from app.services.ai.audit_query_service import AuditQueryService

    svc = AuditQueryService()
    result = svc.get_course_history(course_id)
    return {"status": "ok", **result}
