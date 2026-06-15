"""
Unit tests for US-BKND-AI-PR01 — Mock Authentication Service.

Tests cover:
- UserContext model creation and defaults
- UserRole enum values
- get_current_user dependency with all headers
- get_current_user dependency with missing headers (defaults)
- get_current_user dependency with invalid role (falls back to instructor)
- AUTH_MOCK_MODE=disabled behavior
- UserContext.is_admin and can_author properties
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from app.models.user_context import UserContext, UserRole
from app.services.ai.mock_auth import (
    _extract_user_context_from_headers,
    get_current_user,
)


class TestUserContextModel:
    """Test UserContext Pydantic model."""

    def test_default_values(self):
        """UserContext created with no args uses sensible defaults."""
        ctx = UserContext()
        assert ctx.user_id == "00000000-0000-0000-0000-000000000001"
        assert ctx.organization_id == "00000000-0000-0000-0000-000000000100"
        assert ctx.role == UserRole.INSTRUCTOR
        assert ctx.email == "mock.instructor@example.com"
        assert ctx.is_authenticated is True

    def test_custom_values(self):
        """UserContext accepts custom values for all fields."""
        ctx = UserContext(
            user_id="custom-user-123",
            organization_id="custom-org-456",
            role=UserRole.ADMIN,
            email="admin@example.com",
            is_authenticated=True,
        )
        assert ctx.user_id == "custom-user-123"
        assert ctx.organization_id == "custom-org-456"
        assert ctx.role == UserRole.ADMIN

    def test_is_admin_property(self):
        """is_admin returns True only for ADMIN role."""
        assert UserContext(role=UserRole.ADMIN).is_admin is True
        assert UserContext(role=UserRole.INSTRUCTOR).is_admin is False
        assert UserContext(role=UserRole.REVIEWER).is_admin is False
        assert UserContext(role=UserRole.LEARNER).is_admin is False

    def test_can_author_property(self):
        """can_author returns True for INSTRUCTOR and ADMIN only."""
        assert UserContext(role=UserRole.INSTRUCTOR).can_author is True
        assert UserContext(role=UserRole.ADMIN).can_author is True
        assert UserContext(role=UserRole.REVIEWER).can_author is False
        assert UserContext(role=UserRole.LEARNER).can_author is False


class TestExtractUserContextFromHeaders:
    """Test header-based identity extraction."""

    def _make_mock_request(self, headers: dict) -> MagicMock:
        """Create a mock FastAPI Request with given headers."""
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.get = lambda key, default=None: headers.get(key, default)
        return request

    def test_all_headers_present(self):
        """User context extracts all values from provided headers."""
        req = self._make_mock_request({
            "X-User-ID": "user-abc-123",
            "X-Organization-ID": "org-xyz-456",
            "X-User-Role": "admin",
            "X-User-Email": "admin@test.com",
        })
        ctx = _extract_user_context_from_headers(req)
        assert ctx.user_id == "user-abc-123"
        assert ctx.organization_id == "org-xyz-456"
        assert ctx.role == UserRole.ADMIN
        assert ctx.email == "admin@test.com"

    def test_missing_headers_use_defaults(self):
        """Missing headers fall back to default mock values."""
        req = self._make_mock_request({})
        ctx = _extract_user_context_from_headers(req)
        assert ctx.user_id == "00000000-0000-0000-0000-000000000001"
        assert ctx.organization_id == "00000000-0000-0000-0000-000000000100"
        assert ctx.role == UserRole.INSTRUCTOR
        assert ctx.email == "mock.instructor@example.com"

    def test_partial_headers(self):
        """Some headers present, others use defaults."""
        req = self._make_mock_request({
            "X-User-ID": "partial-user-789",
            "X-User-Role": "reviewer",
        })
        ctx = _extract_user_context_from_headers(req)
        assert ctx.user_id == "partial-user-789"
        assert ctx.role == UserRole.REVIEWER
        # These should use defaults
        assert ctx.organization_id == "00000000-0000-0000-0000-000000000100"
        assert ctx.email == "mock.instructor@example.com"

    def test_invalid_role_falls_back_to_instructor(self):
        """Unrecognized role string defaults to INSTRUCTOR."""
        req = self._make_mock_request({
            "X-User-Role": "superuser",  # Not in UserRole enum
        })
        ctx = _extract_user_context_from_headers(req)
        assert ctx.role == UserRole.INSTRUCTOR

    def test_all_valid_roles(self):
        """All UserRole enum values are correctly parsed from headers."""
        for role in UserRole:
            req = self._make_mock_request({"X-User-Role": role.value})
            ctx = _extract_user_context_from_headers(req)
            assert ctx.role == role


@pytest.mark.asyncio
class TestGetCurrentUserDependency:
    """Test the FastAPI dependency function."""

    def _make_mock_request(self, headers: dict, state=None) -> MagicMock:
        """Create a mock Request with headers and optional state."""
        req = MagicMock()
        req.headers = MagicMock()
        req.headers.get = lambda key, default=None: headers.get(key, default)
        if state is not None:
            req.state = state
        else:
            req.state = MagicMock()
        return req

    async def test_returns_user_context(self):
        """Dependency returns a valid UserContext."""
        req = self._make_mock_request({
            "X-User-ID": "dep-user-001",
            "X-Organization-ID": "dep-org-001",
            "X-User-Role": "instructor",
        })
        ctx = await get_current_user(req)
        assert isinstance(ctx, UserContext)
        assert ctx.user_id == "dep-user-001"

    async def test_attaches_to_request_state(self):
        """UserContext is attached to request.state for downstream use."""
        req = self._make_mock_request({
            "X-User-ID": "state-user-001",
        })
        ctx = await get_current_user(req)
        assert req.state.user_context is ctx
        assert req.state.user_context.user_id == "state-user-001"

    @patch.dict(os.environ, {"AUTH_MOCK_MODE": "disabled"})
    async def test_mock_mode_disabled_raises_501(self):
        """When AUTH_MOCK_MODE=disabled, dependency raises 501."""
        from fastapi import HTTPException
        req = self._make_mock_request({})
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(req)
        assert exc_info.value.status_code == 501
        assert "not yet implemented" in exc_info.value.detail.lower()

    @patch.dict(os.environ, {"AUTH_MOCK_MODE": "enabled"})
    async def test_mock_mode_enabled_works(self):
        """When AUTH_MOCK_MODE=enabled, dependency works normally."""
        req = self._make_mock_request({"X-User-ID": "mock-user"})
        ctx = await get_current_user(req)
        assert ctx.user_id == "mock-user"


class TestUserRoleEnum:
    """Test UserRole enum values."""

    def test_all_roles_defined(self):
        """All four expected roles are defined."""
        roles = [r.value for r in UserRole]
        assert "instructor" in roles
        assert "reviewer" in roles
        assert "admin" in roles
        assert "learner" in roles

    def test_role_from_string(self):
        """Roles can be constructed from string values."""
        assert UserRole("instructor") == UserRole.INSTRUCTOR
        assert UserRole("admin") == UserRole.ADMIN

    def test_invalid_role_raises(self):
        """Invalid role string raises ValueError."""
        with pytest.raises(ValueError):
            UserRole("nonexistent_role")
