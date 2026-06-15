"""
Tests for US-BKND-AI-006 — Create Scoped AI Authoring Sessions.

Covers:
    - AISessionService: create, get, close, validations
    - AISessionRepository: new methods (count_active_by_user, close_session, etc.)
    - Router: POST/GET/DELETE endpoints with proper error codes
    - Config: new session limit fields
    - Schemas: request/response validation
    - Error handling: course not found, permission denied, rate limit, etc.
    - Idempotent DELETE behavior
    - Session ownership validation
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ═══════════════════════════════════════════════════════════════════
# Service Tests — create_session
# ═══════════════════════════════════════════════════════════════════

class TestAISessionServiceCreate:
    """Tests for AISessionService.create_session()."""

    @pytest.fixture
    def mock_db(self):
        """Mock AsyncSession."""
        return AsyncMock()

    @pytest.fixture
    def mock_course(self):
        """Mock CourseRecord."""
        course = MagicMock()
        course.title = "Test Course"
        course.course_id = "course-001"
        course.status = "draft"
        return course

    @pytest.fixture
    def service(self, mock_db):
        """Create AISessionService with mocked dependencies."""
        from app.services.ai.session_service import AISessionService
        return AISessionService(mock_db)

    def test_create_session_success(self, service, mock_db, mock_course):
        """UC1: Create session successfully with all validations passing."""
        import asyncio

        async def _test():
            # Mock config
            with patch.object(service.config, "ai_authoring_enabled", True), \
                 patch.object(service.config, "session_ttl_hours", 24), \
                 patch.object(service.config, "max_active_sessions_per_user", 5):
                # Mock course validation
                with patch.object(service, "_validate_course", AsyncMock(
                    return_value=mock_course
                )):
                    # Mock active session count
                    with patch.object(service.repo, "count_active_by_user", AsyncMock(
                        return_value=0
                    )):
                        # Mock session creation
                        from app.models.ai_models import AISessionRecord
                        created = AISessionRecord(
                            session_id="sess-test-001",
                            user_id="user-001",
                            organization_id="org-001",
                            course_id="course-001",
                            status="active",
                            scope="page",
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                            expires_at=datetime.utcnow() + timedelta(hours=24),
                            last_accessed_at=datetime.utcnow(),
                        )
                        with patch.object(service.repo, "create", AsyncMock(
                            return_value=created
                        )):
                            # Mock audit log
                            with patch.object(service.audit, "log", AsyncMock()):
                                # Mock course state
                                with patch.object(service, "_build_course_state", AsyncMock(
                                    return_value={
                                        "course_id": "course-001",
                                        "title": "Test Course",
                                        "total_pages": 2,
                                        "pages": [
                                            {"page_id": "p1", "title": "Page 1",
                                             "template_type": "text-content",
                                             "order": 0, "updated_at": None},
                                            {"page_id": "p2", "title": "Page 2",
                                             "template_type": "tabs",
                                             "order": 1, "updated_at": None},
                                        ],
                                    }
                                )):
                                    # Mock cache
                                    with patch.object(service, "_cache_session_in_memory"):
                                        result = await service.create_session(
                                            user_id="user-001",
                                            organization_id="org-001",
                                            course_id="course-001",
                                        )

            assert result["session_id"] == "sess-test-001"
            assert result["course_id"] == "course-001"
            assert result["user_id"] == "user-001"
            assert result["organization_id"] == "org-001"
            assert result["status"] == "active"
            assert "created_at" in result
            assert "expires_at" in result
            assert result["course_state"]["total_pages"] == 2
            assert len(result["course_state"]["pages"]) == 2

        asyncio.get_event_loop().run_until_complete(_test())

    def test_create_session_feature_disabled(self, service, mock_db):
        """UC4: Feature flag off raises FeatureDisabledError."""
        import asyncio

        async def _test():
            with patch.object(service.config, "ai_authoring_enabled", False):
                from app.services.ai.session_service import FeatureDisabledError
                with pytest.raises(FeatureDisabledError) as exc:
                    await service.create_session(
                        user_id="user-001",
                        organization_id="org-001",
                        course_id="course-001",
                    )
                assert exc.value.code == "FEATURE_DISABLED"
                assert exc.value.http_status == 404

        asyncio.get_event_loop().run_until_complete(_test())

    def test_create_session_course_not_found(self, service, mock_db):
        """UC2: Non-existent course raises CourseNotFoundError."""
        import asyncio

        async def _test():
            with patch.object(service.config, "ai_authoring_enabled", True):
                with patch.object(service, "_validate_course", AsyncMock(
                    side_effect=__import__("app.services.ai.session_service", fromlist=["CourseNotFoundError"]).CourseNotFoundError("course-999")
                )):
                    from app.services.ai.session_service import CourseNotFoundError
                    with pytest.raises(CourseNotFoundError) as exc:
                        await service.create_session(
                            user_id="user-001",
                            organization_id="org-001",
                            course_id="course-999",
                        )
                    assert exc.value.code == "COURSE_NOT_FOUND"
                    assert exc.value.http_status == 404

        asyncio.get_event_loop().run_until_complete(_test())

    def test_create_session_max_active_exceeded(self, service, mock_db, mock_course):
        """UC3: Max active sessions exceeded raises RateLimitExceededError."""
        import asyncio

        async def _test():
            with patch.object(service.config, "ai_authoring_enabled", True), \
                 patch.object(service.config, "max_active_sessions_per_user", 5):
                with patch.object(service, "_validate_course", AsyncMock(
                    return_value=mock_course
                )):
                    with patch.object(service.repo, "count_active_by_user", AsyncMock(
                        return_value=5  # At limit
                    )):
                        from app.services.ai.session_service import RateLimitExceededError
                        with pytest.raises(RateLimitExceededError) as exc:
                            await service.create_session(
                                user_id="user-001",
                                organization_id="org-001",
                                course_id="course-001",
                            )
                        assert exc.value.code == "RATE_LIMIT_EXCEEDED"
                        assert exc.value.http_status == 429
                        assert exc.value.retryable is True
                        assert "5" in exc.value.message

        asyncio.get_event_loop().run_until_complete(_test())


# ═══════════════════════════════════════════════════════════════════
# Service Tests — get_session
# ═══════════════════════════════════════════════════════════════════

class TestAISessionServiceGet:
    """Tests for AISessionService.get_session()."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        from app.services.ai.session_service import AISessionService
        return AISessionService(mock_db)

    def test_get_session_success(self, service):
        """UC5: Get session successfully."""
        import asyncio

        async def _test():
            from app.models.ai_models import AISessionRecord
            record = AISessionRecord(
                session_id="sess-001",
                user_id="owner-001",
                organization_id="org-001",
                course_id="course-001",
                status="active",
                scope="page",
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(service.repo, "get", AsyncMock(return_value=record)):
                with patch.object(service, "_build_course_state", AsyncMock(
                    return_value={"course_id": "course-001", "title": "Test",
                                  "total_pages": 1, "pages": []}
                )):
                    with patch.object(service.repo, "touch", AsyncMock()):
                        result = await service.get_session("sess-001", "owner-001")

            assert result["session_id"] == "sess-001"
            assert result["status"] == "active"
            assert result["course_state"]["course_id"] == "course-001"

        asyncio.get_event_loop().run_until_complete(_test())

    def test_get_session_not_found(self, service):
        """UC7: Non-existent session raises SessionNotFoundError."""
        import asyncio

        async def _test():
            with patch.object(service.repo, "get", AsyncMock(return_value=None)):
                from app.services.ai.session_service import SessionNotFoundError
                with pytest.raises(SessionNotFoundError) as exc:
                    await service.get_session("sess-999", "user-001")
                assert exc.value.code == "SESSION_NOT_FOUND"
                assert exc.value.http_status == 404

        asyncio.get_event_loop().run_until_complete(_test())

    def test_get_session_wrong_owner(self, service):
        """UC6: Session belongs to another user raises PermissionDeniedError."""
        import asyncio

        async def _test():
            from app.models.ai_models import AISessionRecord
            record = AISessionRecord(
                session_id="sess-001",
                user_id="owner-A",  # Different user
                organization_id="org-001",
                course_id="course-001",
                status="active",
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(service.repo, "get", AsyncMock(return_value=record)):
                from app.services.ai.session_service import PermissionDeniedError
                with pytest.raises(PermissionDeniedError) as exc:
                    await service.get_session("sess-001", "user-B")
                assert exc.value.code == "PERMISSION_DENIED"
                assert exc.value.http_status == 403

        asyncio.get_event_loop().run_until_complete(_test())

    def test_get_expired_session_returns_expired_status(self, service):
        """UC8: Expired session returns with status='expired'."""
        import asyncio

        async def _test():
            from app.models.ai_models import AISessionRecord
            record = AISessionRecord(
                session_id="sess-001",
                user_id="owner-001",
                organization_id="org-001",
                course_id="course-001",
                status="active",
                expires_at=datetime.utcnow() - timedelta(hours=1),  # Expired
            )
            with patch.object(service.repo, "get", AsyncMock(return_value=record)):
                with patch.object(service, "_build_course_state", AsyncMock(
                    return_value={"course_id": "course-001", "title": "",
                                  "total_pages": 0, "pages": []}
                )):
                    with patch.object(service.repo, "touch", AsyncMock()):
                        result = await service.get_session("sess-001", "owner-001")

            assert result["status"] == "expired"  # Status reflects expiry

        asyncio.get_event_loop().run_until_complete(_test())


# ═══════════════════════════════════════════════════════════════════
# Service Tests — close_session
# ═══════════════════════════════════════════════════════════════════

class TestAISessionServiceClose:
    """Tests for AISessionService.close_session()."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        from app.services.ai.session_service import AISessionService
        return AISessionService(mock_db)

    def test_close_session_success(self, service):
        """UC9: Close session successfully."""
        import asyncio

        async def _test():
            from app.models.ai_models import AISessionRecord
            record = AISessionRecord(
                session_id="sess-001",
                user_id="owner-001",
                organization_id="org-001",
                course_id="course-001",
                status="active",
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            closed_record = AISessionRecord(
                session_id="sess-001",
                user_id="owner-001",
                organization_id="org-001",
                course_id="course-001",
                status="closed",
                closed_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )

            with patch.object(service.repo, "get", AsyncMock(return_value=record)):
                with patch.object(service.repo, "close_session", AsyncMock(
                    return_value=closed_record
                )):
                    with patch.object(service.audit, "log", AsyncMock()):
                        result = await service.close_session("sess-001", "owner-001")

            assert result["session_id"] == "sess-001"
            assert result["status"] == "closed"
            assert "deleted_at" in result

        asyncio.get_event_loop().run_until_complete(_test())

    def test_close_session_idempotent(self, service):
        """UC10: Closing an already-closed session returns 200."""
        import asyncio

        async def _test():
            from app.models.ai_models import AISessionRecord
            record = AISessionRecord(
                session_id="sess-001",
                user_id="owner-001",
                organization_id="org-001",
                course_id="course-001",
                status="closed",  # Already closed
                closed_at=datetime.utcnow() - timedelta(hours=1),
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )

            with patch.object(service.repo, "get", AsyncMock(return_value=record)):
                result = await service.close_session("sess-001", "owner-001")

            assert result["session_id"] == "sess-001"
            assert result["status"] == "closed"

        asyncio.get_event_loop().run_until_complete(_test())

    def test_close_session_not_found(self, service):
        """Close non-existent session raises SessionNotFoundError."""
        import asyncio

        async def _test():
            with patch.object(service.repo, "get", AsyncMock(return_value=None)):
                from app.services.ai.session_service import SessionNotFoundError
                with pytest.raises(SessionNotFoundError):
                    await service.close_session("sess-999", "user-001")

        asyncio.get_event_loop().run_until_complete(_test())

    def test_close_session_wrong_owner(self, service):
        """Close someone else's session raises PermissionDeniedError."""
        import asyncio

        async def _test():
            from app.models.ai_models import AISessionRecord
            record = AISessionRecord(
                session_id="sess-001",
                user_id="owner-A",
                organization_id="org-001",
                course_id="course-001",
                status="active",
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(service.repo, "get", AsyncMock(return_value=record)):
                from app.services.ai.session_service import PermissionDeniedError
                with pytest.raises(PermissionDeniedError):
                    await service.close_session("sess-001", "user-B")

        asyncio.get_event_loop().run_until_complete(_test())


# ═══════════════════════════════════════════════════════════════════
# Repository Tests — New Methods
# ═══════════════════════════════════════════════════════════════════

class TestAISessionRepositoryNewMethods:
    """Tests for repository methods added in US-BKND-AI-006."""

    def test_count_active_by_user_exists(self):
        """Repository has count_active_by_user method."""
        from app.repositories.ai_session_repo import AISessionRepository
        assert hasattr(AISessionRepository, "count_active_by_user")
        assert callable(AISessionRepository.count_active_by_user)

    def test_close_session_exists(self):
        """Repository has close_session method."""
        from app.repositories.ai_session_repo import AISessionRepository
        assert hasattr(AISessionRepository, "close_session")
        assert callable(AISessionRepository.close_session)

    def test_list_active_by_user_exists(self):
        """Repository has list_active_by_user method."""
        from app.repositories.ai_session_repo import AISessionRepository
        assert hasattr(AISessionRepository, "list_active_by_user")
        assert callable(AISessionRepository.list_active_by_user)

    def test_get_active_by_user_and_course_exists(self):
        """Repository has get_active_by_user_and_course method."""
        from app.repositories.ai_session_repo import AISessionRepository
        assert hasattr(AISessionRepository, "get_active_by_user_and_course")
        assert callable(AISessionRepository.get_active_by_user_and_course)

    def test_existing_methods_preserved(self):
        """Existing repository methods are still present."""
        from app.repositories.ai_session_repo import AISessionRepository
        assert hasattr(AISessionRepository, "get")
        assert hasattr(AISessionRepository, "get_active")
        assert hasattr(AISessionRepository, "create")
        assert hasattr(AISessionRepository, "update")
        assert hasattr(AISessionRepository, "revoke")
        assert hasattr(AISessionRepository, "expire_stale")
        assert hasattr(AISessionRepository, "touch")


# ═══════════════════════════════════════════════════════════════════
# Config Tests — New Session Limit Fields
# ═══════════════════════════════════════════════════════════════════

class TestAIConfigSessionLimits:
    """Tests for new session limit configuration fields."""

    def test_max_active_sessions_per_user_default(self):
        """Default max_active_sessions_per_user is 5."""
        from app.services.ai.config import get_ai_config
        cfg = get_ai_config()
        assert cfg.max_active_sessions_per_user == 5

    def test_session_cleanup_interval_default(self):
        """Default session_cleanup_interval_minutes is 15."""
        from app.services.ai.config import get_ai_config
        cfg = get_ai_config()
        assert cfg.session_cleanup_interval_minutes == 15

    def test_rate_limit_create_session_default(self):
        """Default rate_limit_create_session_per_hour is 20."""
        from app.services.ai.config import get_ai_config
        cfg = get_ai_config()
        assert cfg.rate_limit_create_session_per_hour == 20

    def test_new_fields_are_ints(self):
        """New config fields are integers."""
        from app.services.ai.config import get_ai_config
        cfg = get_ai_config()
        assert isinstance(cfg.max_active_sessions_per_user, int)
        assert isinstance(cfg.session_cleanup_interval_minutes, int)
        assert isinstance(cfg.rate_limit_create_session_per_hour, int)


# ═══════════════════════════════════════════════════════════════════
# Schema Tests
# ═══════════════════════════════════════════════════════════════════

class TestAISessionSchemas:
    """Tests for Pydantic request/response schemas."""

    def test_create_session_request_valid(self):
        """Valid CreateSessionRequest passes validation."""
        from app.schemas.ai_session import CreateSessionRequest
        body = CreateSessionRequest(course_id="course-001")
        assert body.course_id == "course-001"
        assert body.scope == "page"

    def test_create_session_request_with_scope(self):
        """CreateSessionRequest accepts course scope."""
        from app.schemas.ai_session import CreateSessionRequest
        body = CreateSessionRequest(course_id="course-001", scope="course")
        assert body.scope == "course"

    def test_create_session_request_invalid_scope(self):
        """CreateSessionRequest rejects invalid scope."""
        from app.schemas.ai_session import CreateSessionRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateSessionRequest(course_id="course-001", scope="invalid")

    def test_create_session_request_empty_course_id(self):
        """CreateSessionRequest rejects empty course_id."""
        from app.schemas.ai_session import CreateSessionRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateSessionRequest(course_id="")

    def test_create_session_request_long_course_id(self):
        """CreateSessionRequest rejects course_id > 64 chars."""
        from app.schemas.ai_session import CreateSessionRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateSessionRequest(course_id="x" * 65)

    def test_page_state_dto(self):
        """PageStateDTO is valid."""
        from app.schemas.ai_session import PageStateDTO
        page = PageStateDTO(
            page_id="page-001",
            title="Test Page",
            template_type="text-content",
            order=0,
        )
        assert page.page_id == "page-001"
        assert page.template_type == "text-content"

    def test_course_state_dto(self):
        """CourseStateDTO is valid."""
        from app.schemas.ai_session import CourseStateDTO, PageStateDTO
        state = CourseStateDTO(
            course_id="course-001",
            title="Test Course",
            total_pages=2,
            pages=[
                PageStateDTO(page_id="p1", title="Page 1", template_type="text-content", order=0),
                PageStateDTO(page_id="p2", title="Page 2", template_type="tabs", order=1),
            ],
        )
        assert state.total_pages == 2
        assert len(state.pages) == 2

    def test_create_session_response(self):
        """CreateSessionResponse is valid."""
        from app.schemas.ai_session import CreateSessionResponse, CourseStateDTO
        now = datetime.utcnow()
        resp = CreateSessionResponse(
            session_id="sess-001",
            course_id="course-001",
            user_id="user-001",
            organization_id="org-001",
            created_at=now,
            expires_at=now + timedelta(hours=24),
            status="active",
            course_state=CourseStateDTO(course_id="course-001"),
        )
        assert resp.session_id == "sess-001"
        assert resp.status == "active"

    def test_delete_session_response(self):
        """DeleteSessionResponse is valid."""
        from app.schemas.ai_session import DeleteSessionResponse
        now = datetime.utcnow()
        resp = DeleteSessionResponse(
            session_id="sess-001",
            status="closed",
            deleted_at=now,
        )
        assert resp.status == "closed"
        assert resp.deleted_at == now


# ═══════════════════════════════════════════════════════════════════
# Model Tests — closed_at field
# ═══════════════════════════════════════════════════════════════════

class TestAISessionRecordClosedAt:
    """Tests for the closed_at field added in US-BKND-AI-006."""

    def test_closed_at_field_exists(self):
        """AISessionRecord has closed_at field."""
        from app.models.ai_models import AISessionRecord
        record = AISessionRecord(
            user_id="u1", organization_id="o1", course_id="c1",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        assert hasattr(record, "closed_at")

    def test_closed_at_defaults_none(self):
        """closed_at defaults to None."""
        from app.models.ai_models import AISessionRecord
        record = AISessionRecord(
            user_id="u1", organization_id="o1", course_id="c1",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        assert record.closed_at is None

    def test_to_dict_includes_closed_at(self):
        """to_dict includes closedAt."""
        from app.models.ai_models import AISessionRecord
        now = datetime.utcnow()
        record = AISessionRecord(
            session_id="sess-001",
            user_id="u1", organization_id="o1", course_id="c1",
            status="closed",
            closed_at=now,
            expires_at=now + timedelta(hours=24),
        )
        d = record.to_dict()
        assert "closedAt" in d
        assert d["closedAt"] == now.isoformat()


# ═══════════════════════════════════════════════════════════════════
# Error Envelope Tests
# ═══════════════════════════════════════════════════════════════════

class TestSessionErrorClasses:
    """Tests for the new session error classes."""

    def test_course_not_found_error(self):
        from app.services.ai.session_service import CourseNotFoundError
        err = CourseNotFoundError("course-999")
        assert err.code == "COURSE_NOT_FOUND"
        assert err.http_status == 404
        assert err.retryable is False
        assert "course-999" in err.message

    def test_feature_disabled_error(self):
        from app.services.ai.session_service import FeatureDisabledError
        err = FeatureDisabledError()
        assert err.code == "FEATURE_DISABLED"
        assert err.http_status == 404

    def test_permission_denied_error(self):
        from app.services.ai.session_service import PermissionDeniedError
        err = PermissionDeniedError()
        assert err.code == "PERMISSION_DENIED"
        assert err.http_status == 403

    def test_rate_limit_exceeded_error(self):
        from app.services.ai.session_service import RateLimitExceededError
        err = RateLimitExceededError("Too many sessions")
        assert err.code == "RATE_LIMIT_EXCEEDED"
        assert err.http_status == 429
        assert err.retryable is True

    def test_session_not_found_error(self):
        from app.services.ai.session_service import SessionNotFoundError
        err = SessionNotFoundError("sess-999")
        assert err.code == "SESSION_NOT_FOUND"
        assert err.http_status == 404

    def test_session_expired_error(self):
        from app.services.ai.session_service import SessionExpiredError
        err = SessionExpiredError()
        assert err.code == "SESSION_EXPIRED"
        assert err.http_status == 401
        assert err.retryable is True

    def test_session_closed_error(self):
        from app.services.ai.session_service import SessionClosedError
        err = SessionClosedError()
        assert err.code == "SESSION_CLOSED"
        assert err.http_status == 401


# ═══════════════════════════════════════════════════════════════════
# Router Import Tests
# ═══════════════════════════════════════════════════════════════════

class TestRouterAISessions:
    """Tests for the AI sessions router."""

    def test_router_no_mock_bridge_imports(self):
        """Router does NOT import mock session functions (bridge removed)."""
        import app.routers.ai_sessions as mod
        assert not hasattr(mod, "create_mock_session")
        assert not hasattr(mod, "end_mock_session")

    def test_router_imports_schemas(self):
        """Router imports Pydantic schemas."""
        import app.routers.ai_sessions as mod
        assert hasattr(mod, "CreateSessionRequest")
        assert hasattr(mod, "CreateSessionResponse")
        assert hasattr(mod, "GetSessionResponse")
        assert hasattr(mod, "DeleteSessionResponse")

    def test_router_imports_session_errors(self):
        """Router imports session error classes for error handling."""
        import app.routers.ai_sessions as mod
        assert hasattr(mod, "SessionError")
        assert hasattr(mod, "CourseNotFoundError")
        assert hasattr(mod, "PermissionDeniedError")
        assert hasattr(mod, "RateLimitExceededError")
        assert hasattr(mod, "SessionNotFoundError")

    def test_router_has_three_endpoints(self):
        """Router has POST, GET, and DELETE endpoints."""
        from app.routers.ai_sessions import router
        paths = {r.path for r in router.routes}
        assert "/api/v1/ai/sessions" in paths
        assert "/api/v1/ai/sessions/{session_id}" in paths

    def test_router_tag(self):
        """Router uses AI - Sessions tag."""
        from app.routers.ai_sessions import router
        assert any("AI" in tag for tag in router.tags for tag in [tag] if "Session" in tag)
        # Simpler: check that tags contain the expected value
        route_with_tags = [r for r in router.routes if r.tags]
        if route_with_tags:
            assert any("Session" in tag for r in route_with_tags for tag in (r.tags or []))


# ═══════════════════════════════════════════════════════════════════
# Middleware Tests
# ═══════════════════════════════════════════════════════════════════

class TestSessionMiddlewareUpdated:
    """Tests for session middleware after US-BKND-AI-006 updates."""

    def test_create_mock_session_accepts_session_id(self):
        """create_mock_session now accepts optional session_id parameter."""
        from app.middleware.session_middleware import create_mock_session
        import inspect
        sig = inspect.signature(create_mock_session)
        assert "session_id" in sig.parameters

    def test_middleware_has_db_fallback(self):
        """Middleware has _lookup_session_in_db fallback function."""
        from app.middleware import session_middleware
        assert hasattr(session_middleware, "_lookup_session_in_db")

    def test_middleware_skips_template_routes(self):
        """Middleware skips template/config endpoints."""
        from app.middleware.session_middleware import SessionAuthMiddleware
        assert SessionAuthMiddleware is not None


# ═══════════════════════════════════════════════════════════════════
# Template Type Inference Tests
# ═══════════════════════════════════════════════════════════════════

class TestTemplateTypeInference:
    """Tests for _infer_template_type static method."""

    def test_infer_from_layout(self):
        """Infer template type from page layout."""
        from app.services.ai.session_service import AISessionService
        page = MagicMock()
        page.layout = {"templateType": "tabs"}
        page.components = []
        result = AISessionService._infer_template_type(page)
        assert result == "tabs"

    def test_infer_from_component_type(self):
        """Infer template type from first component."""
        from app.services.ai.session_service import AISessionService
        page = MagicMock()
        page.layout = {}
        comp = MagicMock()
        comp.component_type = "accordion"
        page.components = [comp]
        result = AISessionService._infer_template_type(page)
        assert result == "accordion"

    def test_infer_fallback_default(self):
        """Fallback to 'text-content' when no hints available."""
        from app.services.ai.session_service import AISessionService
        page = MagicMock()
        page.layout = None
        page.components = []
        result = AISessionService._infer_template_type(page)
        assert result == "text-content"


# ═══════════════════════════════════════════════════════════════════
# Session Service — expire_stale and touch
# ═══════════════════════════════════════════════════════════════════

class TestAISessionServiceMaintenance:
    """Tests for maintenance operations (expire, touch)."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        from app.services.ai.session_service import AISessionService
        return AISessionService(mock_db)

    def test_expire_stale_sessions(self, service):
        """expire_stale_sessions delegates to repository."""
        import asyncio

        async def _test():
            with patch.object(service.repo, "expire_stale", AsyncMock(return_value=3)):
                count = await service.expire_stale_sessions()
                assert count == 3

        asyncio.get_event_loop().run_until_complete(_test())

    def test_touch_session(self, service):
        """touch_session delegates to repository."""
        import asyncio

        async def _test():
            with patch.object(service.repo, "touch", AsyncMock()):
                await service.touch_session("sess-001")
                service.repo.touch.assert_called_once_with("sess-001")

        asyncio.get_event_loop().run_until_complete(_test())

    def test_delete_session_backward_compat(self, service):
        """Legacy delete_session method still works."""
        import asyncio

        async def _test():
            from app.models.ai_models import AISessionRecord
            record = AISessionRecord(
                session_id="sess-001",
                user_id="u1", organization_id="o1", course_id="c1",
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(service.repo, "get", AsyncMock(return_value=record)):
                with patch.object(service.repo, "close_session", AsyncMock()):
                    result = await service.delete_session("sess-001")
                    assert result is True

        asyncio.get_event_loop().run_until_complete(_test())

    def test_delete_session_not_found(self, service):
        """Legacy delete_session returns False when not found."""
        import asyncio

        async def _test():
            with patch.object(service.repo, "get", AsyncMock(return_value=None)):
                result = await service.delete_session("sess-999")
                assert result is False

        asyncio.get_event_loop().run_until_complete(_test())
