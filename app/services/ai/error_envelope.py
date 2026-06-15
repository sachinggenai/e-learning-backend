"""
Standardized AI error envelope.

All AI endpoints return errors in a consistent format so the frontend
and AI agent can handle errors uniformly without inspecting status codes.

Per FR-4 of US-BKND-AI-003:
    {"status": "error", "code": "ERROR_CODE", "message": "...",
     "details": {...}, "retryable": true|false}

Usage in AI routers:
    from app.services.ai.error_envelope import ai_error
    return ai_error("SESSION_EXPIRED", "Your session has expired", status=440)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse


# ── Error code constants ─────────────────────────────────────────

class AIErrorCode:
    """Standardized AI error codes as defined in US-BKND-AI-003 Section 2.3."""

    AI_NOT_CONFIGURED = "AI_NOT_CONFIGURED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_INVALID = "SESSION_INVALID"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CROSS_TENANT_DENIED = "CROSS_TENANT_DENIED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    PROPOSAL_ALREADY_APPLIED = "PROPOSAL_ALREADY_APPLIED"
    STALE_DATA = "STALE_DATA"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# ── Error metadata ──────────────────────────────────────────────

_ERROR_METADATA: Dict[str, Dict[str, Any]] = {
    AIErrorCode.AI_NOT_CONFIGURED: {
        "http_status": 503,
        "retryable": False,
        "description": "AI feature enabled but not configured",
    },
    AIErrorCode.SESSION_EXPIRED: {
        "http_status": 440,
        "retryable": False,
        "description": "Session token has expired",
    },
    AIErrorCode.SESSION_INVALID: {
        "http_status": 401,
        "retryable": False,
        "description": "Session token not found or malformed",
    },
    AIErrorCode.PERMISSION_DENIED: {
        "http_status": 403,
        "retryable": False,
        "description": "User lacks access to requested resource",
    },
    AIErrorCode.CROSS_TENANT_DENIED: {
        "http_status": 403,
        "retryable": False,
        "description": "Resource belongs to different organization",
    },
    AIErrorCode.VALIDATION_ERROR: {
        "http_status": 422,
        "retryable": True,
        "description": "Schema or business rule validation failed",
    },
    AIErrorCode.PROPOSAL_EXPIRED: {
        "http_status": 409,
        "retryable": False,
        "description": "Proposal TTL has elapsed",
    },
    AIErrorCode.PROPOSAL_ALREADY_APPLIED: {
        "http_status": 409,
        "retryable": False,
        "description": "Proposal has already been applied",
    },
    AIErrorCode.STALE_DATA: {
        "http_status": 409,
        "retryable": True,
        "description": "Base hash mismatch — re-fetch and retry",
    },
    AIErrorCode.CONFIRMATION_REQUIRED: {
        "http_status": 400,
        "retryable": False,
        "description": "Destructive operation needs explicit confirmation",
    },
    AIErrorCode.RATE_LIMIT_EXCEEDED: {
        "http_status": 429,
        "retryable": True,
        "description": "Too many requests; retry after N seconds",
    },
    AIErrorCode.TOKEN_BUDGET_EXCEEDED: {
        "http_status": 429,
        "retryable": False,
        "description": "Request exceeds token budget",
    },
    AIErrorCode.MODEL_UNAVAILABLE: {
        "http_status": 503,
        "retryable": True,
        "description": "AI model provider unavailable",
    },
    AIErrorCode.NOT_FOUND: {
        "http_status": 404,
        "retryable": False,
        "description": "Requested resource not found",
    },
    AIErrorCode.INTERNAL_ERROR: {
        "http_status": 500,
        "retryable": False,
        "description": "Unexpected server error",
    },
}


def ai_error(
    code: str,
    message: str,
    status: Optional[int] = None,
    retryable: Optional[bool] = None,
    **details: Any,
) -> JSONResponse:
    """Build a standardized AI error response.

    Args:
        code: One of AIErrorCode constants (e.g. "SESSION_EXPIRED").
        message: Human-readable error message.
        status: HTTP status code. If None, inferred from error code metadata.
        retryable: Whether the client can retry. If None, inferred from metadata.
        **details: Additional structured detail fields (e.g. retry_after_seconds=30).

    Returns:
        JSONResponse with the standardized error envelope.

    Example:
        return ai_error(
            AIErrorCode.SESSION_EXPIRED,
            "Your session has expired. Please create a new one.",
            retry_after_seconds=0,
        )
    """
    metadata = _ERROR_METADATA.get(code, {})

    if status is None:
        status = metadata.get("http_status", 500)

    if retryable is None:
        retryable = metadata.get("retryable", False)

    body: Dict[str, Any] = {
        "status": "error",
        "code": code,
        "message": message,
        "details": details or {},
        "retryable": retryable,
    }

    return JSONResponse(status_code=status, content=body)


def ai_error_from_http_exception(
    code: str,
    message: str,
    status: int = 400,
    retryable: bool = False,
    **details: Any,
) -> JSONResponse:
    """Convenience wrapper when you already know the exact HTTP status.

    Unlike ai_error(), this does NOT consult error metadata — it uses
    exactly the values you pass. Useful when wrapping existing HTTPException
    patterns into the AI error envelope.

    Example:
        return ai_error_from_http_exception(
            "VALIDATION_ERROR", "Title is required", status=422, retryable=True
        )
    """
    return JSONResponse(
        status_code=status,
        content={
            "status": "error",
            "code": code,
            "message": message,
            "details": details or {},
            "retryable": retryable,
        },
    )
