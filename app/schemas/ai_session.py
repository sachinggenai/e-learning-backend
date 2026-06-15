"""Pydantic schemas for AI Session API requests and responses.

Implements the contracts defined in US-BKND-AI-006 Section 2.1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


# ── Request Schemas ───────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    """Request body for POST /api/v1/ai/sessions."""
    course_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Course ID string for the course to author with AI",
        examples=["course-101"],
    )
    scope: str = Field(
        default="page",
        pattern=r"^(page|course)$",
        description="Session scope: 'page' for page-level, 'course' for course-level",
    )


# ── Response Sub-Schemas ──────────────────────────────────────────

class PageStateDTO(BaseModel):
    """A page in the course state snapshot."""
    page_id: str = Field(..., description="Unique page identifier")
    title: str = Field(..., description="Page title")
    template_type: str = Field(
        default="text-content",
        description="Inferred template type for the page",
    )
    order: int = Field(default=0, description="Page order in the course")
    updated_at: Optional[str] = Field(
        default=None, description="ISO-8601 last-updated timestamp"
    )


class CourseStateDTO(BaseModel):
    """Course state snapshot included in session responses."""
    course_id: str = Field(..., description="Course identifier")
    title: str = Field(default="", description="Course title")
    total_pages: int = Field(default=0, description="Total number of pages")
    pages: List[PageStateDTO] = Field(
        default_factory=list,
        description="List of pages in the course",
    )


# ── Response Schemas ──────────────────────────────────────────────

class CreateSessionResponse(BaseModel):
    """Response body for POST /api/v1/ai/sessions (201 Created)."""
    session_id: str = Field(..., description="UUID v4 session identifier")
    course_id: str = Field(..., description="Course ID this session is scoped to")
    user_id: str = Field(..., description="User ID who owns the session")
    organization_id: str = Field(..., description="Organization ID for tenant isolation")
    created_at: datetime = Field(..., description="Session creation timestamp (UTC)")
    expires_at: datetime = Field(..., description="Session expiry timestamp (UTC)")
    status: str = Field(default="active", description="Session status")
    course_state: CourseStateDTO = Field(
        default_factory=CourseStateDTO,
        description="Current course state snapshot",
    )


class GetSessionResponse(BaseModel):
    """Response body for GET /api/v1/ai/sessions/{session_id} (200 OK)."""
    session_id: str = Field(..., description="UUID v4 session identifier")
    course_id: str = Field(..., description="Course ID this session is scoped to")
    user_id: str = Field(..., description="User ID who owns the session")
    organization_id: str = Field(..., description="Organization ID")
    created_at: datetime = Field(..., description="Session creation timestamp (UTC)")
    expires_at: datetime = Field(..., description="Session expiry timestamp (UTC)")
    status: str = Field(..., description="Session status: active, expired, or closed")
    course_state: CourseStateDTO = Field(
        default_factory=CourseStateDTO,
        description="Current course state snapshot (live from DB)",
    )


class DeleteSessionResponse(BaseModel):
    """Response body for DELETE /api/v1/ai/sessions/{session_id} (200 OK)."""
    session_id: str = Field(..., description="UUID v4 session identifier")
    status: str = Field(default="closed", description="Always 'closed' after deletion")
    deleted_at: datetime = Field(..., description="Timestamp when session was closed")
