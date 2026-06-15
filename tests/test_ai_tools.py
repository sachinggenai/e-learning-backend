"""
Tests for US-BKND-AI-007 — List and Fetch Course Pages for AI Context.

Covers:
    - ToolExecutor: list_pages, fetch_page, session validation, error handling
    - Router: POST /tools/list_pages, POST /tools/fetch_page
    - Page etag computation
    - Template type inference
    - Course scope enforcement
    - Error code coverage (PAGE_NOT_FOUND, SESSION_EXPIRED, etc.)
    - Idempotent read behavior
    - Audit logging
"""

import pytest
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ═══════════════════════════════════════════════════════════════════
# ToolExecutor Unit Tests — list_pages
# ═══════════════════════════════════════════════════════════════════

class TestToolExecutorListPages:
    """Tests for ToolExecutor list_pages tool."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        from app.services.ai.tool_executor import ToolExecutor
        return ToolExecutor(mock_db)

    def _make_session(self, session_id="sess-001", user_id="user-001",
                      course_id="course-001", organization_id="org-001",
                      expired=False, closed=False):
        from app.models.ai_models import AISessionRecord
        status = "closed" if closed else "active"
        expires = datetime.utcnow() - timedelta(hours=1) if expired else \
                  datetime.utcnow() + timedelta(hours=24)
        return AISessionRecord(
            session_id=session_id, user_id=user_id,
            organization_id=organization_id, course_id=course_id,
            status=status, expires_at=expires,
        )

    def _make_page(self, page_id="page-001", course_id="course-001",
                   title="Test Page", order_index=0, components=None):
        from app.models.page_component import PageRecord
        page = MagicMock(spec=PageRecord)
        page.page_id = page_id
        page.course_id = course_id
        page.title = title
        page.order_index = order_index
        page.layout = None
        page.components = components or []
        page.created_at = datetime(2026, 6, 14, 10, 0, 0)
        page.updated_at = datetime(2026, 6, 14, 12, 0, 0)

        def to_dict(include_components=True):
            d = {
                "pageId": page_id,
                "title": title,
                "order": order_index,
                "layout": None,
                "theme": None,
                "pageCompletion": None,
                "createdAt": "2026-06-14T10:00:00",
                "updatedAt": "2026-06-14T12:00:00",
            }
            if include_components:
                d["components"] = []
            return d
        page.to_dict = to_dict
        return page

    def test_list_pages_empty_course(self, executor):
        """FR-8: Course with zero pages returns empty list."""
        import asyncio
        async def _test():
            session = self._make_session()
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "list_by_course", AsyncMock(
                    return_value=[]
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        result = await executor.execute(
                            "list_pages", {"session_id": "sess-001"}, "user-001"
                        )

            assert result["status"] == "success"
            assert result["data"]["pages"] == []
            assert result["data"]["total_pages"] == 0

        asyncio.get_event_loop().run_until_complete(_test())

    def test_list_pages_with_pages_ordered(self, executor):
        """FR-3: Returns ordered pages with correct metadata."""
        import asyncio
        async def _test():
            session = self._make_session(course_id="course-001")
            page_a = self._make_page("p-a", course_id="course-001", title="Alpha", order_index=0)
            page_b = self._make_page("p-b", course_id="course-001", title="Beta", order_index=1)
            page_c = self._make_page("p-c", course_id="course-001", title="Gamma", order_index=2)

            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "list_by_course", AsyncMock(
                    return_value=[page_a, page_b, page_c]
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        result = await executor.execute(
                            "list_pages", {"session_id": "sess-001"}, "user-001"
                        )

            assert result["status"] == "success"
            pages = result["data"]["pages"]
            assert len(pages) == 3
            assert result["data"]["total_pages"] == 3
            assert pages[0]["page_id"] == "p-a"
            assert pages[0]["title"] == "Alpha"
            assert pages[0]["order"] == 0
            assert pages[1]["page_id"] == "p-b"
            assert pages[1]["order"] == 1
            assert pages[2]["page_id"] == "p-c"
            assert pages[2]["order"] == 2

        asyncio.get_event_loop().run_until_complete(_test())

    def test_list_pages_includes_page_etag(self, executor):
        """FR-6: Each page includes a page_etag."""
        import asyncio
        async def _test():
            session = self._make_session()
            page = self._make_page("p-1")
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "list_by_course", AsyncMock(
                    return_value=[page]
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        result = await executor.execute(
                            "list_pages", {"session_id": "sess-001"}, "user-001"
                        )

            p = result["data"]["pages"][0]
            assert "page_etag" in p
            assert len(p["page_etag"]) == 64  # SHA-256 hex
            assert all(c in "0123456789abcdef" for c in p["page_etag"])

        asyncio.get_event_loop().run_until_complete(_test())

    def test_list_pages_etag_changes_with_content(self, executor):
        """page_etag changes when page content changes."""
        page_a = self._make_page("p-1", title="Version A")
        page_b = self._make_page("p-1", title="Version B")
        # Override to_dict to return different content
        def td_a(ic=True):
            return {"pageId": "p-1", "title": "Version A", "order": 0, "components": []}
        def td_b(ic=True):
            return {"pageId": "p-1", "title": "Version B", "order": 0, "components": []}
        page_a.to_dict = td_a
        page_b.to_dict = td_b

        etag_a = executor._compute_page_etag(page_a)
        etag_b = executor._compute_page_etag(page_b)
        assert etag_a != etag_b
        assert len(etag_a) == 64
        assert len(etag_b) == 64

    def test_list_pages_etag_stable(self, executor):
        """Same page content produces same etag."""
        page1 = self._make_page("p-1")
        page2 = self._make_page("p-1")  # Identical
        etag1 = executor._compute_page_etag(page1)
        etag2 = executor._compute_page_etag(page2)
        assert etag1 == etag2


# ═══════════════════════════════════════════════════════════════════
# ToolExecutor Unit Tests — fetch_page
# ═══════════════════════════════════════════════════════════════════

class TestToolExecutorFetchPage:
    """Tests for ToolExecutor fetch_page tool."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        from app.services.ai.tool_executor import ToolExecutor
        return ToolExecutor(mock_db)

    def _make_session(self, **kw):
        from app.models.ai_models import AISessionRecord
        return AISessionRecord(
            session_id=kw.get("session_id", "sess-001"),
            user_id=kw.get("user_id", "user-001"),
            organization_id=kw.get("organization_id", "org-001"),
            course_id=kw.get("course_id", "course-001"),
            status=kw.get("status", "active"),
            expires_at=kw.get("expires_at", datetime.utcnow() + timedelta(hours=24)),
        )

    def _make_page_with_components(self, page_id="page-001", course_id="course-001",
                                    title="Test Page", order_index=0):
        from app.models.page_component import PageRecord
        page = MagicMock(spec=PageRecord)
        page.page_id = page_id
        page.course_id = course_id
        page.title = title
        page.order_index = order_index
        page.layout = {"templateType": "tabs"}
        page.theme_config = None
        page.completion_config = {"strategy": "all"}
        page.created_at = datetime(2026, 6, 14, 10, 0, 0)
        page.updated_at = datetime(2026, 6, 14, 12, 0, 0)

        comp = MagicMock()
        comp.component_id = "comp-001"
        comp.component_type = "content-text"
        comp.order_index = 0
        comp.data = {"content": "<p>Hello</p>"}
        comp.audio_config = None
        comp.completion_criteria = None
        comp.styling = None
        comp.created_at = datetime(2026, 6, 14, 10, 0, 0)
        comp.updated_at = datetime(2026, 6, 14, 12, 0, 0)
        page.components = [comp]

        def to_dict(include_components=True):
            d = {
                "pageId": page_id,
                "title": title,
                "order": order_index,
                "layout": {"templateType": "tabs"},
                "theme": None,
                "pageCompletion": {"strategy": "all"},
                "createdAt": "2026-06-14T10:00:00",
                "updatedAt": "2026-06-14T12:00:00",
            }
            if include_components:
                d["components"] = [{
                    "componentId": "comp-001",
                    "componentType": "content-text",
                    "order": 0,
                    "data": {"content": "<p>Hello</p>"},
                    "audioConfig": None,
                    "completionCriteria": None,
                    "styling": None,
                    "createdAt": "2026-06-14T10:00:00",
                    "updatedAt": "2026-06-14T12:00:00",
                }]
            return d
        page.to_dict = to_dict
        return page

    def test_fetch_page_success(self, executor):
        """FR-5: Returns full page with components."""
        import asyncio
        async def _test():
            session = self._make_session(course_id="course-001")
            page = self._make_page_with_components("page-001", "course-001")

            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "get_by_course_and_page", AsyncMock(
                    return_value=page
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        result = await executor.execute(
                            "fetch_page",
                            {"session_id": "sess-001", "page_id": "page-001"},
                            "user-001"
                        )

            assert result["status"] == "success"
            data = result["data"]
            assert data["page_id"] == "page-001"
            assert data["title"] == "Test Page"
            assert data["order"] == 0
            assert "page_etag" in data
            assert len(data["components"]) == 1
            assert data["components"][0]["component_type"] == "content-text"
            assert data["components"][0]["component_id"] == "comp-001"

        asyncio.get_event_loop().run_until_complete(_test())

    def test_fetch_page_not_found(self, executor):
        """FR-9: Non-existent page returns 404 PAGE_NOT_FOUND."""
        import asyncio
        async def _test():
            session = self._make_session()
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                # get_by_course_and_page returns None
                with patch.object(executor.page_repo, "get_by_course_and_page", AsyncMock(
                    return_value=None
                )):
                    # get (by page_id only) also returns None
                    with patch.object(executor.page_repo, "get", AsyncMock(
                        return_value=None
                    )):
                        with patch.object(executor.audit_svc, "log", AsyncMock()):
                            result = await executor.execute(
                                "fetch_page",
                                {"session_id": "sess-001", "page_id": "non-existent"},
                                "user-001"
                            )

            assert result["status"] == "error"
            assert result["code"] == "PAGE_NOT_FOUND"
            assert result["_http_status"] == 404
            assert result["retryable"] is False

        asyncio.get_event_loop().run_until_complete(_test())

    def test_fetch_page_cross_course_rejected(self, executor):
        """FR-2: Page from different course returns 403 PERMISSION_DENIED."""
        import asyncio
        async def _test():
            session = self._make_session(course_id="course-A")
            page_in_other_course = MagicMock()
            page_in_other_course.course_id = "course-B"
            page_in_other_course.page_id = "page-001"

            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "get_by_course_and_page", AsyncMock(
                    return_value=None  # Not found in course-A
                )):
                    with patch.object(executor.page_repo, "get", AsyncMock(
                        return_value=page_in_other_course  # Exists in course-B
                    )):
                        with patch.object(executor.audit_svc, "log", AsyncMock()):
                            result = await executor.execute(
                                "fetch_page",
                                {"session_id": "sess-001", "page_id": "page-001"},
                                "user-001"
                            )

            assert result["status"] == "error"
            assert result["code"] == "PERMISSION_DENIED"
            assert result["_http_status"] == 403

        asyncio.get_event_loop().run_until_complete(_test())

    def test_fetch_page_missing_page_id(self, executor):
        """Missing page_id returns VALIDATION_ERROR."""
        import asyncio
        async def _test():
            session = self._make_session()
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.audit_svc, "log", AsyncMock()):
                    result = await executor.execute(
                        "fetch_page",
                        {"session_id": "sess-001", "page_id": ""},
                        "user-001"
                    )

            assert result["status"] == "error"
            assert result["code"] == "VALIDATION_ERROR"

        asyncio.get_event_loop().run_until_complete(_test())


# ═══════════════════════════════════════════════════════════════════
# ToolExecutor Unit Tests — Session Validation
# ═══════════════════════════════════════════════════════════════════

class TestToolExecutorSessionValidation:
    """Tests for session validation in ToolExecutor."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        from app.services.ai.tool_executor import ToolExecutor
        return ToolExecutor(mock_db)

    def test_missing_session_id(self, executor):
        """Missing session_id returns VALIDATION_ERROR."""
        import asyncio
        async def _test():
            with patch.object(executor.audit_svc, "log", AsyncMock()):
                result = await executor.execute(
                    "list_pages", {"session_id": ""}, "user-001"
                )
            assert result["status"] == "error"
            assert result["code"] == "VALIDATION_ERROR"
            assert result["_http_status"] == 400

        asyncio.get_event_loop().run_until_complete(_test())

    def test_expired_session(self, executor):
        """Expired session returns SESSION_EXPIRED with 440."""
        import asyncio
        async def _test():
            from app.models.ai_models import AISessionRecord
            expired = AISessionRecord(
                session_id="sess-expired",
                user_id="user-001",
                organization_id="org-001",
                course_id="course-001",
                status="active",
                expires_at=datetime.utcnow() - timedelta(hours=1),
            )
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=None
            )):
                with patch.object(executor.session_repo, "get", AsyncMock(
                    return_value=expired
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        result = await executor.execute(
                            "list_pages", {"session_id": "sess-expired"}, "user-001"
                        )

            assert result["status"] == "error"
            assert result["code"] == "SESSION_EXPIRED"
            assert result["_http_status"] == 440

        asyncio.get_event_loop().run_until_complete(_test())

    def test_closed_session(self, executor):
        """Closed session returns SESSION_CLOSED."""
        import asyncio
        async def _test():
            from app.models.ai_models import AISessionRecord
            closed = AISessionRecord(
                session_id="sess-closed",
                user_id="user-001",
                organization_id="org-001",
                course_id="course-001",
                status="closed",
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=None
            )):
                with patch.object(executor.session_repo, "get", AsyncMock(
                    return_value=closed
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        result = await executor.execute(
                            "list_pages", {"session_id": "sess-closed"}, "user-001"
                        )

            assert result["status"] == "error"
            assert result["code"] == "SESSION_CLOSED"
            assert result["_http_status"] == 401

        asyncio.get_event_loop().run_until_complete(_test())

    def test_invalid_session(self, executor):
        """Non-existent session returns SESSION_INVALID."""
        import asyncio
        async def _test():
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=None
            )):
                with patch.object(executor.session_repo, "get", AsyncMock(
                    return_value=None
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        result = await executor.execute(
                            "list_pages", {"session_id": "sess-unknown"}, "user-001"
                        )

            assert result["status"] == "error"
            assert result["code"] == "SESSION_INVALID"
            assert result["_http_status"] == 401

        asyncio.get_event_loop().run_until_complete(_test())

    def test_wrong_user_session(self, executor):
        """Session owned by different user returns PERMISSION_DENIED."""
        import asyncio
        async def _test():
            from app.models.ai_models import AISessionRecord
            session = AISessionRecord(
                session_id="sess-001",
                user_id="owner-A",  # Different from caller
                organization_id="org-001",
                course_id="course-001",
                status="active",
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.audit_svc, "log", AsyncMock()):
                    result = await executor.execute(
                        "list_pages", {"session_id": "sess-001"}, "user-B"
                    )

            assert result["status"] == "error"
            assert result["code"] == "PERMISSION_DENIED"
            assert result["_http_status"] == 403

        asyncio.get_event_loop().run_until_complete(_test())

    def test_unknown_tool(self, executor):
        """Unknown tool name returns UNKNOWN_TOOL."""
        import asyncio
        async def _test():
            from app.models.ai_models import AISessionRecord
            session = AISessionRecord(
                session_id="sess-001", user_id="user-001",
                organization_id="org-001", course_id="course-001",
                status="active", expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.audit_svc, "log", AsyncMock()):
                    result = await executor.execute(
                        "nonexistent_tool", {"session_id": "sess-001"}, "user-001"
                    )

            assert result["status"] == "error"
            assert result["code"] == "UNKNOWN_TOOL"

        asyncio.get_event_loop().run_until_complete(_test())


# ═══════════════════════════════════════════════════════════════════
# Template Type Inference Tests
# ═══════════════════════════════════════════════════════════════════

class TestTemplateTypeInference:
    """Tests for _derive_template_type method."""

    def test_from_layout_templateType(self):
        from app.services.ai.tool_executor import ToolExecutor
        page = MagicMock()
        page.layout = {"templateType": "tabs"}
        page.components = []
        assert ToolExecutor._derive_template_type(page) == "tabs"

    def test_from_layout_template_id(self):
        from app.services.ai.tool_executor import ToolExecutor
        page = MagicMock()
        page.layout = {"template_id": "accordion-layout"}
        page.components = []
        assert ToolExecutor._derive_template_type(page) == "accordion-layout"

    def test_from_first_component(self):
        from app.services.ai.tool_executor import ToolExecutor
        page = MagicMock()
        page.layout = None
        comp = MagicMock()
        comp.component_type = "click-reveal"
        page.components = [comp]
        assert ToolExecutor._derive_template_type(page) == "click-reveal"

    def test_fallback_unknown(self):
        from app.services.ai.tool_executor import ToolExecutor
        page = MagicMock()
        page.layout = None
        page.components = []
        assert ToolExecutor._derive_template_type(page) == "unknown"


# ═══════════════════════════════════════════════════════════════════
# Page Etag Tests
# ═══════════════════════════════════════════════════════════════════

class TestPageEtag:
    """Tests for _compute_page_etag."""

    def test_etag_is_sha256_hex(self):
        from app.services.ai.tool_executor import ToolExecutor
        page = MagicMock()
        page.to_dict = lambda include_components=True: {"pageId": "p1", "title": "Test"}
        etag = ToolExecutor._compute_page_etag(page)
        assert len(etag) == 64
        assert all(c in "0123456789abcdef" for c in etag)

    def test_etag_deterministic(self):
        from app.services.ai.tool_executor import ToolExecutor
        page = MagicMock()
        page.to_dict = lambda include_components=True: {"pageId": "p1", "title": "Test"}
        etag1 = ToolExecutor._compute_page_etag(page)
        etag2 = ToolExecutor._compute_page_etag(page)
        assert etag1 == etag2

    def test_etag_different_for_different_content(self):
        from app.services.ai.tool_executor import ToolExecutor
        page1 = MagicMock()
        page1.to_dict = lambda include_components=True: {"pageId": "p1", "title": "A"}
        page2 = MagicMock()
        page2.to_dict = lambda include_components=True: {"pageId": "p1", "title": "B"}
        assert ToolExecutor._compute_page_etag(page1) != ToolExecutor._compute_page_etag(page2)


# ═══════════════════════════════════════════════════════════════════
# ToolError Tests
# ═══════════════════════════════════════════════════════════════════

class TestToolError:
    """Tests for the ToolError exception class."""

    def test_basic_error(self):
        from app.services.ai.tool_executor import ToolError
        err = ToolError("TEST_CODE", "Test message", 418, True, {"key": "val"})
        assert err.code == "TEST_CODE"
        assert err.message == "Test message"
        assert err.http_status == 418
        assert err.retryable is True
        assert err.details == {"key": "val"}

    def test_defaults(self):
        from app.services.ai.tool_executor import ToolError
        err = ToolError("TEST", "msg")
        assert err.http_status == 400
        assert err.retryable is False
        assert err.details == {}

    def test_error_response_formatting(self):
        from app.services.ai.tool_executor import ToolError, ToolExecutor
        err = ToolError("PAGE_NOT_FOUND", "Page not found", 404, False,
                        {"page_id": "p1"})
        resp = ToolExecutor._error_response(err)
        assert resp["status"] == "error"
        assert resp["code"] == "PAGE_NOT_FOUND"
        assert resp["_http_status"] == 404
        assert resp["details"] == {"page_id": "p1"}


# ═══════════════════════════════════════════════════════════════════
# Router Tests
# ═══════════════════════════════════════════════════════════════════

class TestRouterAITools:
    """Tests for AI tools router endpoints."""

    def test_router_has_list_pages(self):
        from app.routers.ai_tools import router
        paths = {r.path: r.methods for r in router.routes}
        assert "/api/v1/ai/tools/list_pages" in paths
        assert "POST" in paths["/api/v1/ai/tools/list_pages"]

    def test_router_has_fetch_page(self):
        from app.routers.ai_tools import router
        paths = {r.path: r.methods for r in router.routes}
        assert "/api/v1/ai/tools/fetch_page" in paths
        assert "POST" in paths["/api/v1/ai/tools/fetch_page"]

    def test_router_has_validate(self):
        from app.routers.ai_tools import router
        paths = {r.path for r in router.routes}
        assert "/api/v1/ai/tools/validate" in paths

    def test_router_no_longer_has_get_stubs(self):
        """The old GET /courses/{id}/pages stubs are removed."""
        from app.routers.ai_tools import router
        paths = {r.path for r in router.routes}
        assert "/api/v1/ai/courses/{course_id}/pages" not in paths
        assert "/api/v1/ai/courses/{course_id}/pages/{page_id}" not in paths

    def test_list_pages_schema_valid(self):
        from app.routers.ai_tools import ListPagesRequest
        body = ListPagesRequest(session_id="sess-001")
        assert body.session_id == "sess-001"

    def test_fetch_page_schema_valid(self):
        from app.routers.ai_tools import FetchPageRequest
        body = FetchPageRequest(session_id="sess-001", page_id="page-001")
        assert body.session_id == "sess-001"
        assert body.page_id == "page-001"

    def test_list_pages_schema_rejects_empty(self):
        from app.routers.ai_tools import ListPagesRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ListPagesRequest(session_id="")

    def test_fetch_page_schema_rejects_empty(self):
        from app.routers.ai_tools import FetchPageRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            FetchPageRequest(session_id="sess-001", page_id="")


# ═══════════════════════════════════════════════════════════════════
# Idempotency Tests
# ═══════════════════════════════════════════════════════════════════

class TestToolIdempotency:
    """FR-10: Both tools are idempotent reads."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    def test_list_pages_idempotent(self, mock_db):
        """Repeated list_pages calls return same data."""
        import asyncio
        async def _test():
            from app.services.ai.tool_executor import ToolExecutor
            from app.models.ai_models import AISessionRecord
            executor = ToolExecutor(mock_db)

            session = AISessionRecord(
                session_id="sess-001", user_id="u1",
                organization_id="o1", course_id="c1",
                status="active", expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            page = MagicMock()
            page.page_id = "p1"; page.title = "Test"; page.order_index = 0
            page.layout = None; page.components = []
            page.created_at = datetime(2026, 6, 14)
            page.updated_at = datetime(2026, 6, 14)
            page.to_dict = lambda ic=True: {"pageId": "p1", "title": "Test", "order": 0, "components": []}

            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "list_by_course", AsyncMock(
                    return_value=[page]
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        r1 = await executor.execute("list_pages", {"session_id": "sess-001"}, "u1")
                        r2 = await executor.execute("list_pages", {"session_id": "sess-001"}, "u1")

            assert r1["data"]["total_pages"] == r2["data"]["total_pages"]
            assert r1["data"]["pages"][0]["page_etag"] == r2["data"]["pages"][0]["page_etag"]

        asyncio.get_event_loop().run_until_complete(_test())

    def test_fetch_page_idempotent(self, mock_db):
        """Repeated fetch_page calls return same data."""
        import asyncio
        async def _test():
            from app.services.ai.tool_executor import ToolExecutor
            from app.models.ai_models import AISessionRecord
            executor = ToolExecutor(mock_db)

            session = AISessionRecord(
                session_id="sess-001", user_id="u1",
                organization_id="o1", course_id="c1",
                status="active", expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            page = MagicMock()
            page.page_id = "p1"; page.title = "Test"; page.order_index = 0
            page.layout = None; page.theme_config = None; page.completion_config = None
            page.components = []
            page.created_at = datetime(2026, 6, 14)
            page.updated_at = datetime(2026, 6, 14)
            page.to_dict = lambda ic=True: {
                "pageId": "p1", "title": "Test", "order": 0,
                "layout": None, "theme": None, "pageCompletion": None,
                "createdAt": "2026-06-14T00:00:00", "updatedAt": "2026-06-14T00:00:00",
                "components": [],
            }

            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "get_by_course_and_page", AsyncMock(
                    return_value=page
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()):
                        r1 = await executor.execute(
                            "fetch_page",
                            {"session_id": "sess-001", "page_id": "p1"}, "u1"
                        )
                        r2 = await executor.execute(
                            "fetch_page",
                            {"session_id": "sess-001", "page_id": "p1"}, "u1"
                        )

            assert r1["data"]["page_etag"] == r2["data"]["page_etag"]
            assert r1["data"]["title"] == r2["data"]["title"]

        asyncio.get_event_loop().run_until_complete(_test())


# ═══════════════════════════════════════════════════════════════════
# Audit Logging Tests
# ═══════════════════════════════════════════════════════════════════

class TestAuditLogging:
    """FR-7: Audit logging on every tool call."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    def test_list_pages_logs_audit(self, mock_db):
        """list_pages successful call logs audit."""
        import asyncio
        async def _test():
            from app.services.ai.tool_executor import ToolExecutor
            from app.models.ai_models import AISessionRecord
            executor = ToolExecutor(mock_db)

            session = AISessionRecord(
                session_id="sess-001", user_id="u1",
                organization_id="o1", course_id="c1",
                status="active", expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "list_by_course", AsyncMock(
                    return_value=[]
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()) as mock_log:
                        await executor.execute(
                            "list_pages", {"session_id": "sess-001"}, "u1"
                        )

            assert mock_log.called
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["session_id"] == "sess-001"
            assert call_kwargs["user_id"] == "u1"
            assert call_kwargs["action"] == "tool.list_pages"

        asyncio.get_event_loop().run_until_complete(_test())

    def test_fetch_page_logs_audit(self, mock_db):
        """fetch_page successful call logs audit."""
        import asyncio
        async def _test():
            from app.services.ai.tool_executor import ToolExecutor
            from app.models.ai_models import AISessionRecord
            executor = ToolExecutor(mock_db)

            session = AISessionRecord(
                session_id="sess-001", user_id="u1",
                organization_id="o1", course_id="c1",
                status="active", expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            page = MagicMock()
            page.page_id = "p1"; page.title = "T"; page.order_index = 0
            page.layout = None; page.theme_config = None; page.completion_config = None
            page.components = []
            page.created_at = datetime(2026, 6, 14)
            page.updated_at = datetime(2026, 6, 14)
            page.to_dict = lambda ic=True: {
                "pageId": "p1", "title": "T", "order": 0,
                "layout": None, "theme": None, "pageCompletion": None,
                "createdAt": "2026-06-14T00:00:00", "updatedAt": "2026-06-14T00:00:00",
                "components": [],
            }

            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "get_by_course_and_page", AsyncMock(
                    return_value=page
                )):
                    with patch.object(executor.audit_svc, "log", AsyncMock()) as mock_log:
                        await executor.execute(
                            "fetch_page",
                            {"session_id": "sess-001", "page_id": "p1"}, "u1"
                        )

            assert mock_log.called
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["session_id"] == "sess-001"
            assert call_kwargs["action"] == "tool.fetch_page"
            assert call_kwargs["target_id"] == "p1"

        asyncio.get_event_loop().run_until_complete(_test())

    def test_audit_failure_does_not_block(self, mock_db):
        """Audit logging failure does not block the tool response."""
        import asyncio
        async def _test():
            from app.services.ai.tool_executor import ToolExecutor
            from app.models.ai_models import AISessionRecord
            executor = ToolExecutor(mock_db)

            session = AISessionRecord(
                session_id="sess-001", user_id="u1",
                organization_id="o1", course_id="c1",
                status="active", expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            with patch.object(executor.session_repo, "get_active", AsyncMock(
                return_value=session
            )):
                with patch.object(executor.page_repo, "list_by_course", AsyncMock(
                    return_value=[]
                )):
                    # Audit raises an exception
                    with patch.object(executor.audit_svc, "log", AsyncMock(
                        side_effect=RuntimeError("DB down")
                    )):
                        result = await executor.execute(
                            "list_pages", {"session_id": "sess-001"}, "u1"
                        )

            # Tool should still succeed despite audit failure
            assert result["status"] == "success"
            assert result["data"]["total_pages"] == 0

        asyncio.get_event_loop().run_until_complete(_test())
