"""Tests for US-BKND-AI-009 — Proposal Lifecycle."""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.ai.proposal_service import (
    AIProposalService, ProposalError, ProposalNotFoundError,
    ProposalStaleError, ProposalConflictError,
)
from app.services.ai.diff_engine import DiffEngine
from app.models.ai_models import AIProposalRecord


class TestDiffEngine:
    def test_create_diff(self):
        de = DiffEngine()
        d = de.compute("create_page", None, {"title": "X", "data": {"c": "hello"}})
        assert d["before"] is None
        assert d["after"] == {"title": "X", "data": {"c": "hello"}}
        assert "title" in d["changed_fields"]

    def test_update_diff(self):
        de = DiffEngine()
        d = de.compute("update_page", {"title": "Old", "data": {}}, {"title": "New", "data": {}})
        assert d["before"] == {"title": "Old", "data": {}}
        assert d["after"] == {"title": "New", "data": {}}
        assert "title" in d["changed_fields"]

    def test_update_no_change(self):
        de = DiffEngine()
        d = de.compute("update_page", {"title": "Same"}, {"title": "Same"})
        assert d["changed_fields"] == []

    def test_delete_diff(self):
        de = DiffEngine()
        d = de.compute("delete_page", {"title": "Gone", "data": {}}, None)
        assert d["before"] == {"title": "Gone", "data": {}}
        assert d["after"] is None
        assert "title" in d["changed_fields"]


class TestErrorClasses:
    def test_not_found(self):
        e = ProposalNotFoundError("pid-1")
        assert e.code == "PROPOSAL_NOT_FOUND" and e.http_status == 404

    def test_stale(self):
        e = ProposalStaleError("expired")
        assert e.code == "PROPOSAL_STALE" and e.http_status == 410

    def test_conflict(self):
        e = ProposalConflictError()
        assert e.code == "CONFLICT_DETECTED" and e.http_status == 409

    def test_base_error(self):
        e = ProposalError("TEST", "msg", 418)
        assert e.code == "TEST" and e.http_status == 418


class TestProposalServiceCreate:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    def _make_session(self):
        from app.models.ai_models import AISessionRecord
        return AISessionRecord(
            session_id="sess-001", user_id="u1", organization_id="o1",
            course_id="course-001", status="active",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )

    def test_create_page_proposal(self, mock_db):
        async def _t():
            svc = AIProposalService(mock_db)
            sess = self._make_session()
            created = AIProposalRecord(
                proposal_id="prop-001", session_id="sess-001", user_id="u1",
                organization_id="o1", course_id="course-001",
                action_type="create_page", target_type="page",
                proposed_changes={}, status="pending",
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(minutes=30),
            )
            with patch.object(svc.session_repo, "get_active", AsyncMock(return_value=sess)):
                with patch.object(svc, "_validate", AsyncMock(return_value=[])):
                    with patch.object(svc.proposal_repo, "create", AsyncMock(return_value=created)):
                        with patch.object(svc.audit, "log", AsyncMock()):
                            r = await svc.create_proposal(
                                "sess-001", "u1", "o1", "course-001",
                                "create_page", "page",
                                {"title": "Test", "template_type": "text-content",
                                 "data": {"content": "Hello"}},
                            )
            assert r["proposal_id"] == "prop-001"
            assert r["status"] == "pending"
            assert r["validation_status"] == "valid"

        asyncio.get_event_loop().run_until_complete(_t())

    def test_create_with_validation_errors(self, mock_db):
        async def _t():
            svc = AIProposalService(mock_db)
            sess = self._make_session()
            created = AIProposalRecord(
                proposal_id="prop-001", session_id="sess-001", user_id="u1",
                organization_id="o1", course_id="course-001",
                action_type="create_page", target_type="page",
                proposed_changes={}, status="pending",
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(minutes=30),
            )
            val_msgs = [{"severity": "error", "code": "MIN_ITEMS_VIOLATION",
                         "field": "data.tabs", "message": "Need at least 2 tabs"}]
            with patch.object(svc.session_repo, "get_active", AsyncMock(return_value=sess)):
                with patch.object(svc, "_validate", AsyncMock(return_value=val_msgs)):
                    with patch.object(svc.proposal_repo, "create", AsyncMock(return_value=created)):
                        with patch.object(svc.audit, "log", AsyncMock()):
                            r = await svc.create_proposal(
                                "sess-001", "u1", "o1", "course-001",
                                "create_page", "page",
                                {"title": "Tabs", "template_type": "tabs",
                                 "data": {"tabs": [{"title": "One"}]}},
                            )
            assert r["validation_status"] == "error"
            assert len(r["validation_messages"]) == 1

        asyncio.get_event_loop().run_until_complete(_t())


class TestProposalServiceApply:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    def _make_record(self, status="pending", expired=False):
        return AIProposalRecord(
            proposal_id="prop-001", session_id="sess-001", user_id="u1",
            organization_id="o1", course_id="course-001",
            action_type="create_page", target_type="page",
            proposed_changes={
                "data_before": None,
                "data_after": {"title": "New Page", "template_type": "text-content",
                               "data": {"content": "Hello"}},
                "data_patch": {"title": "New Page", "template_type": "text-content",
                               "data": {"content": "Hello"}},
                "diff": {},
                "validation_status": "valid",
                "validation_messages": [],
            },
            status=status,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() - timedelta(hours=1) if expired
                       else datetime.utcnow() + timedelta(minutes=30),
        )

    def test_apply_success(self, mock_db):
        async def _t():
            svc = AIProposalService(mock_db)
            record = self._make_record()
            with patch.object(svc.proposal_repo, "get", AsyncMock(return_value=record)):
                with patch.object(svc, "_execute", AsyncMock(return_value={
                    "resource_id": "page-new", "operation": "create_page",
                    "resource_type": "page", "changes_summary": "Page created",
                })):
                    with patch.object(svc.proposal_repo, "update", AsyncMock()):
                        with patch.object(svc.audit, "log", AsyncMock()):
                            r = await svc.apply_proposal("prop-001", "sess-001", "u1")
            assert r["status"] == "applied"

        asyncio.get_event_loop().run_until_complete(_t())

    def test_apply_expired(self, mock_db):
        async def _t():
            svc = AIProposalService(mock_db)
            record = self._make_record(expired=True)
            with patch.object(svc.proposal_repo, "get", AsyncMock(return_value=record)):
                with patch.object(svc.proposal_repo, "update", AsyncMock()):
                    try:
                        await svc.apply_proposal("prop-001", "sess-001", "u1")
                        assert False
                    except ProposalStaleError as e:
                        assert e.http_status == 410

        asyncio.get_event_loop().run_until_complete(_t())

    def test_apply_idempotent(self, mock_db):
        async def _t():
            svc = AIProposalService(mock_db)
            record = self._make_record(status="applied")
            record.applied_at = datetime.utcnow()
            with patch.object(svc.proposal_repo, "get", AsyncMock(return_value=record)):
                r = await svc.apply_proposal("prop-001", "sess-001", "u1")
            assert r["status"] == "applied"

        asyncio.get_event_loop().run_until_complete(_t())


class TestProposalServiceCancel:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    def _make_record(self, status="pending"):
        return AIProposalRecord(
            proposal_id="prop-001", session_id="sess-001", user_id="u1",
            organization_id="o1", course_id="course-001",
            action_type="create_page", target_type="page",
            proposed_changes={}, status=status,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )

    def test_cancel_success(self, mock_db):
        async def _t():
            svc = AIProposalService(mock_db)
            record = self._make_record()
            with patch.object(svc.proposal_repo, "get", AsyncMock(return_value=record)):
                with patch.object(svc.proposal_repo, "update", AsyncMock()):
                    with patch.object(svc.audit, "log", AsyncMock()):
                        r = await svc.cancel_proposal("prop-001", "sess-001", "u1")
            assert r["status"] == "cancelled"

        asyncio.get_event_loop().run_until_complete(_t())


class TestRouter:
    def test_endpoints_exist(self):
        from app.routers.ai_proposals import router
        paths = {(r.methods or set(), r.path) for r in router.routes}
        # POST /proposals
        assert any("POST" in m and p == "/api/v1/ai/proposals" for m, p in paths)
        # GET /proposals
        assert any("GET" in m and p == "/api/v1/ai/proposals" for m, p in paths)

    def test_schemas(self):
        from app.routers.ai_proposals import (
            CreateProposalRequest, ApplyProposalRequest, CancelProposalRequest
        )
        c = CreateProposalRequest(session_id="s1", operation="create_page",
                                   data={"title": "T"})
        assert c.operation == "create_page"
        a = ApplyProposalRequest(user_confirmed=True)
        assert a.user_confirmed is True
        x = CancelProposalRequest(reason="Changed mind")
        assert x.reason == "Changed mind"
