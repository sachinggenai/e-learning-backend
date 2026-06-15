"""AI Tool Executor Service — US-BKND-AI-007.

Orchestrates the execution of registered AI tools: input validation, session
checking, permission scoping, rate limiting, repository calls, and audit logging.

Stateless executor that can be created per-request with a DB session.

Implemented tools:
    list_pages  — Return ordered page metadata for a course
    fetch_page  — Return full page content with components

Future tools (other stories):
    US-BKND-AI-009/010/011/012: Proposal lifecycle tools
    US-BKND-AI-049: Confirmation token tools

TODOs:
    US-BKND-AI-021: Add rate limiting via RateLimiter service
    US-BKND-AI-012: Add propose_update, propose_create tools
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_session_repo import AISessionRepository
from app.repositories.page_component_repo import PageRepository
from app.repositories.ai_audit_repo import AIAuditRepository
from app.services.ai.audit_service import AIAuditService

logger = logging.getLogger("ai_authoring")


class ToolError(Exception):
    """Structured error for tool execution failures."""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 400,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)


class ToolExecutor:
    """Stateless executor for AI tool calls.

    Created per-request with injected repositories. Handles
    session validation, course scope enforcement, repository
    calls, etag computation, audit logging, and error formatting.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_repo = AISessionRepository(db)
        self.page_repo = PageRepository(db)
        self.audit_svc = AIAuditService(db)

    # ── Public entry point ────────────────────────────────────────

    async def execute(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        caller_user_id: str,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        """Validate session, enforce scope, run tool, audit, return result.

        Args:
            tool_name: Registered tool name (e.g. "list_pages", "fetch_page").
            payload: Request body dict containing at least "session_id".
            caller_user_id: Authenticated user ID from auth dependency.
            ip_address: Client IP for audit trail.

        Returns:
            Dict with "status" ("success"|"error") and "data" or error details.
        """
        # 1. Extract and validate session
        session_id = payload.get("session_id", "")
        if not session_id:
            return self._error_response(
                ToolError("VALIDATION_ERROR", "session_id is required", 400)
            )

        session = await self.session_repo.get_active(session_id)
        if session is None:
            # Check if session exists but is expired/closed
            existing = await self.session_repo.get(session_id)
            if existing is not None:
                if existing.is_expired():
                    return self._error_response(
                        ToolError("SESSION_EXPIRED",
                                  "Session has expired. Please create a new session.",
                                  440)
                    )
                if existing.status == "closed":
                    return self._error_response(
                        ToolError("SESSION_CLOSED",
                                  "This session has been closed.",
                                  401)
                    )
            return self._error_response(
                ToolError("SESSION_INVALID",
                          "Session not found or invalid.",
                          401)
            )

        # Ownership check
        if session.user_id != caller_user_id:
            return self._error_response(
                ToolError("PERMISSION_DENIED",
                          "Session does not belong to the authenticated user.",
                          403)
            )

        # 2. Route to tool handler
        try:
            if tool_name == "list_pages":
                result = await self._handle_list_pages(session.course_id)
            elif tool_name == "fetch_page":
                page_id = payload.get("page_id", "")
                result = await self._handle_fetch_page(session.course_id, page_id)
            else:
                return self._error_response(
                    ToolError("UNKNOWN_TOOL", f"Unknown tool: '{tool_name}'", 400)
                )
        except ToolError as err:
            return self._error_response(err)
        except Exception:
            logger.exception("Error executing tool '%s'", tool_name)
            return self._error_response(
                ToolError("SERVER_ERROR",
                          "An unexpected error occurred while processing the request.",
                          503, retryable=True)
            )

        # 3. Audit log (fire-and-forget — audit failures don't block the response)
        try:
            await self.audit_svc.log(
                session_id=session_id,
                user_id=caller_user_id,
                organization_id=session.organization_id,
                course_id=session.course_id,
                action=f"tool.{tool_name}",
                target_type="page" if tool_name == "fetch_page" else "course",
                target_id=payload.get("page_id", session.course_id),
                details={
                    "tool_name": tool_name,
                    "result_status": result.get("status", "unknown"),
                },
                ip_address=ip_address,
            )
        except Exception:
            logger.warning("Audit log failed for tool '%s' — non-blocking", tool_name)

        return result

    # ── Tool handlers ─────────────────────────────────────────────

    async def _handle_list_pages(self, course_id: str) -> Dict[str, Any]:
        """Return ordered page metadata for a course.

        FR-3: Returns page_id, title, template_type, order, page_etag,
        created_at, updated_at for every page in the course.
        FR-4: Includes total_pages.
        FR-8: Empty course returns {pages: [], total_pages: 0}.
        FR-10: Idempotent read — no mutations.
        """
        pages = await self.page_repo.list_by_course(course_id)
        page_list = []
        for p in pages:
            page_list.append({
                "page_id": p.page_id,
                "title": p.title,
                "template_type": self._derive_template_type(p),
                "order": p.order_index,
                "page_etag": self._compute_page_etag(p),
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            })

        return {
            "status": "success",
            "data": {
                "pages": page_list,
                "total_pages": len(page_list),
            },
        }

    async def _handle_fetch_page(
        self, course_id: str, page_id: str
    ) -> Dict[str, Any]:
        """Return full page content with components.

        FR-5: Returns page_id, title, order, layout, theme, page_completion,
        components[], created_at, updated_at, page_etag.
        FR-2: Course scope enforcement — page must belong to session's course.
        FR-6: page_etag computed for staleness detection.
        FR-9: Non-existent page returns 404.
        FR-10: Idempotent read — no mutations.
        """
        if not page_id:
            raise ToolError("VALIDATION_ERROR", "page_id is required", 400)

        page = await self.page_repo.get_by_course_and_page(course_id, page_id)
        if page is None:
            # Check if page exists in a different course (for better error)
            page_anywhere = await self.page_repo.get(page_id)
            if page_anywhere is not None and page_anywhere.course_id != course_id:
                raise ToolError(
                    "PERMISSION_DENIED",
                    f"Page '{page_id}' does not belong to the session's course.",
                    403,
                    details={"page_id": page_id, "course_id": course_id},
                )
            raise ToolError(
                "PAGE_NOT_FOUND",
                f"Page '{page_id}' not found in course '{course_id}'.",
                404,
                details={"page_id": page_id, "course_id": course_id},
            )

        page_dict = page.to_dict(include_components=True)
        page_dict["page_etag"] = self._compute_page_etag(page)

        # Rename keys to match API contract
        result = {
            "page_id": page_dict.get("pageId", page.page_id),
            "title": page_dict.get("title", page.title),
            "order": page_dict.get("order", page.order_index),
            "layout": page_dict.get("layout"),
            "theme": page_dict.get("theme"),
            "page_completion": page_dict.get("pageCompletion"),
            "page_etag": page_dict["page_etag"],
            "components": [
                {
                    "component_id": c.get("componentId"),
                    "component_type": c.get("componentType"),
                    "order": c.get("order"),
                    "data": c.get("data", {}),
                    "audio_config": c.get("audioConfig"),
                    "completion_criteria": c.get("completionCriteria"),
                    "styling": c.get("styling"),
                    "created_at": c.get("createdAt"),
                    "updated_at": c.get("updatedAt"),
                }
                for c in page_dict.get("components", [])
            ],
            "created_at": page_dict.get("createdAt"),
            "updated_at": page_dict.get("updatedAt"),
        }

        return {"status": "success", "data": result}

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _derive_template_type(page) -> str:
        """Infer the primary template type from page layout or first component.

        Checks layout.templateType, layout.template_id, then falls back
        to the first component's component_type. Returns "unknown" if
        no hints are available.
        """
        layout = getattr(page, "layout", None)
        if isinstance(layout, dict):
            ttype = layout.get("templateType") or layout.get("template_id")
            if ttype:
                return ttype

        components = getattr(page, "components", None)
        if components and len(components) > 0:
            first = components[0]
            ctype = getattr(first, "component_type", None)
            if ctype:
                return ctype

        return "unknown"

    @staticmethod
    def _compute_page_etag(page) -> str:
        """Compute a deterministic SHA-256 hash of the page for staleness detection.

        Uses the page's to_dict() serialization sorted by key for
        deterministic output. This allows the AI agent to detect
        concurrent modifications between list and fetch operations.

        FR-6: Every page response includes a page_etag for staleness
        detection in subsequent proposal calls (US-AI-008/009).
        """
        page_dict = page.to_dict(include_components=True)
        # Sort by key for deterministic serialization
        raw = json.dumps(page_dict, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _error_response(err: ToolError) -> Dict[str, Any]:
        """Format a ToolError into the standard error response envelope."""
        return {
            "status": "error",
            "code": err.code,
            "message": err.message,
            "details": err.details,
            "retryable": err.retryable,
            "_http_status": err.http_status,
        }
