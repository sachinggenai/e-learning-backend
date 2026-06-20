"""REST endpoint for similar course queries — US-BKND-AI-015.

Optional REST API for admin/UI access outside the AI tool context.
Primary integration remains via ToolExecutor → ChatOrchestrator.

Route: POST /api/v1/ai/similar-courses
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.services.ai.similar_course_service import (
    SimilarCourseService,
    FeatureDisabledError,
    SessionValidationError,
)
from app.services.ai.error_envelope import ai_error

logger = logging.getLogger("ai_authoring")
router = APIRouter(prefix="/api/v1/ai", tags=["AI - Similar Courses"])


class SimilarCourseQueryRequest(BaseModel):
    session_id: Optional[str] = Field(
        default=None, min_length=1, max_length=128,
        description="Active AI session ID. Optional for admin queries.",
    )
    query: str = Field(
        ..., min_length=1, max_length=500,
        description="Natural language query",
    )
    max_results: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict] = Field(default=None)


@router.post("/similar-courses")
async def query_similar_courses(
    body: SimilarCourseQueryRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Search for similar courses within the user's organization.

    Feature-flag gated: FEATURE_SIMILAR_COURSE_RETRIEVAL must be true.
    Results are ADVISORY ONLY — never authoritative for API contracts,
    template schemas, or validation rules.
    """
    service = SimilarCourseService(db)

    try:
        result = await service.query_similar_courses(
            session_id=body.session_id or "",
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
        logger.exception("Unexpected error in similar course query")
        return ai_error(
            "SERVER_ERROR",
            "An unexpected error occurred while searching for similar courses.",
            status=503,
        )
