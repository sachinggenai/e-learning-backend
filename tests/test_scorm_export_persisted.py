"""
Tests for:
  - POST /api/v1/export/scorm/{courseId}?format=... (persisted SCORM export)
  - PUT  /api/v1/courses/{courseId}               (upsert endpoint)
"""
import os
import io
import re
import json
import zipfile
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from app.main import app as real_app
from app.db.config import get_session

# ── import all ORM models so their tables are registered on Base.metadata ──────
from app.models.base import Base
import app.models.persisted_course  # noqa: F401 – registers CourseRecord etc.
import app.models.page_component    # noqa: F401 – registers PageRecord / ComponentRecord

TEST_DB_URL = "sqlite+aiosqlite:///./test_scorm_export_persisted.db"

if os.path.exists("test_scorm_export_persisted.db"):
    os.remove("test_scorm_export_persisted.db")


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def test_app():
    engine = create_async_engine(TEST_DB_URL, future=True, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_session():
        async with session_factory() as session:
            yield session

    real_app.dependency_overrides[get_session] = _override_session
    yield real_app

    real_app.dependency_overrides.clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper: seed a course + optional page + optional component
# ---------------------------------------------------------------------------

async def _seed_course(client: AsyncClient, course_id: str = "export-c1", title: str = "Test Course") -> dict:
    payload = {"courseId": course_id, "title": title, "description": None, "data": {}}
    r = await client.post("/api/v1/courses", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _seed_page(client: AsyncClient, course_id: str, page_title: str = "Page 1") -> dict:
    r = await client.post(f"/api/v1/courses/{course_id}/pages", json={"title": page_title, "order": 0})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _seed_component(client: AsyncClient, page_id: str) -> dict:
    r = await client.post(f"/api/v1/pages/{page_id}/components", json={
        "componentType": "content-text",
        "order": 0,
        "data": {"text": "Hello"},
    })
    assert r.status_code in (200, 201), r.text
    return r.json()


# ===========================================================================
# Tests: PUT /api/v1/courses/{courseId}  (upsert)
# ===========================================================================

@pytest.mark.asyncio
async def test_upsert_creates_new_course(test_app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "upsert-new-001"
        r = await client.put(f"/api/v1/courses/{cid}", json={
            "courseId": cid,
            "title": "Upserted Course",
            "description": "desc",
            "data": {},
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["courseId"] == cid
        assert body["title"] == "Upserted Course"


@pytest.mark.asyncio
async def test_upsert_updates_existing_course(test_app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "upsert-update-001"
        # First, create via POST
        await client.post("/api/v1/courses", json={
            "courseId": cid, "title": "Original", "description": None, "data": {},
        })

        # Now upsert with new title
        r = await client.put(f"/api/v1/courses/{cid}", json={
            "courseId": cid,
            "title": "Updated via Upsert",
            "description": "new desc",
            "data": {},
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["title"] == "Updated via Upsert"


@pytest.mark.asyncio
async def test_upsert_is_idempotent(test_app: FastAPI):
    """Calling PUT twice with the same payload should not create duplicates."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "upsert-idem-001"
        payload = {"courseId": cid, "title": "Idempotent", "description": None, "data": {}}

        r1 = await client.put(f"/api/v1/courses/{cid}", json=payload)
        assert r1.status_code == 201

        r2 = await client.put(f"/api/v1/courses/{cid}", json=payload)
        assert r2.status_code == 200, r2.text

        # Should still be a single record in the list
        list_r = await client.get("/api/v1/courses")
        ids = [c["courseId"] for c in list_r.json()]
        assert ids.count(cid) == 1


@pytest.mark.asyncio
async def test_upsert_response_includes_pages_and_components(test_app: FastAPI):
    """PUT upsert response should return hydrated pages[] like GET does."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "upsert-pages-001"
        create = await client.put(
            f"/api/v1/courses/{cid}",
            json={
                "courseId": cid,
                "title": "Course With Pages",
                "description": None,
                "data": {},
            },
        )
        assert create.status_code == 201, create.text
        assert create.json().get("pages") == []

        page_resp = await client.post(
            f"/api/v1/courses/{cid}/pages",
            json={"title": "P1", "order": 0},
        )
        assert page_resp.status_code in (200, 201), page_resp.text
        page_id = page_resp.json()["pageId"]

        comp_resp = await client.post(
            f"/api/v1/courses/{cid}/pages/{page_id}/components",
            json={
                "componentType": "content-text",
                "order": 0,
                "data": {"text": "hello"},
            },
        )
        assert comp_resp.status_code in (200, 201), comp_resp.text

        upsert = await client.put(
            f"/api/v1/courses/{cid}",
            json={
                "courseId": cid,
                "title": "Course With Pages Updated",
                "description": None,
                "data": {},
            },
        )
        assert upsert.status_code == 200, upsert.text
        body = upsert.json()
        assert isinstance(body.get("pages"), list)
        assert len(body["pages"]) == 1
        assert body["pages"][0]["pageId"] == page_id
        assert isinstance(body["pages"][0].get("components"), list)
        assert len(body["pages"][0]["components"]) == 1


# ===========================================================================
# Tests: POST /api/v1/export/scorm/{courseId}  (persisted SCORM export)
# ===========================================================================

@pytest.mark.asyncio
async def test_export_404_for_missing_course(test_app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        r = await client.post("/api/v1/export/scorm/nonexistent-course")
        assert r.status_code == 404
        body = r.json()
        assert "nonexistent-course" in body.get("detail", "")


@pytest.mark.asyncio
async def test_export_422_course_no_pages(test_app: FastAPI):
    """Course exists but has no pages → structured 422 with COURSE_NO_PAGES."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "export-nopage-001"
        await _seed_course(client, course_id=cid, title="Empty Course")

        r = await client.post(f"/api/v1/export/scorm/{cid}")
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, list), "detail must be an array"
        codes = [e["code"] for e in detail]
        assert "COURSE_NO_PAGES" in codes, f"Expected COURSE_NO_PAGES, got {codes}"


@pytest.mark.asyncio
async def test_export_422_page_no_components(test_app: FastAPI):
    """Course has a page but the page has no components → PAGE_NO_COMPONENTS."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "export-nocomp-001"
        await _seed_course(client, course_id=cid, title="No Comp Course")

        # Create page via pages endpoint
        await client.post(f"/api/v1/courses/{cid}/pages", json={"title": "Empty Page", "order": 0})

        r = await client.post(f"/api/v1/export/scorm/{cid}")
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, list)
        codes = [e["code"] for e in detail]
        assert "PAGE_NO_COMPONENTS" in codes, f"Expected PAGE_NO_COMPONENTS, got {codes}"


@pytest.mark.asyncio
async def test_export_422_structured_fields(test_app: FastAPI):
    """Each error in the 422 detail array must have the required fields."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "export-fields-001"
        await _seed_course(client, course_id=cid)

        r = await client.post(f"/api/v1/export/scorm/{cid}")
        assert r.status_code == 422
        detail = r.json()["detail"]
        for err in detail:
            assert "code" in err, f"Missing 'code' in {err}"
            assert "field" in err, f"Missing 'field' in {err}"
            assert "message" in err, f"Missing 'message' in {err}"


@pytest.mark.asyncio
async def test_export_format_query_param_accepted(test_app: FastAPI):
    """No request body should be needed; format as query param works."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "export-qparam-001"
        await _seed_course(client, course_id=cid)

        # Should NOT get a 422 about missing body — only about empty course
        r = await client.post(f"/api/v1/export/scorm/{cid}?format=scorm_1_2")
        # With empty course, expect 422 (content error) not 422 about request body
        assert r.status_code in (200, 404, 422)
        if r.status_code == 422:
            detail = r.json()["detail"]
            # Must be our structured array, not a Pydantic request body error
            assert isinstance(detail, list)
            for e in detail:
                assert isinstance(e, dict), "detail items must be dicts"
                # Pydantic body errors have 'loc', ours don't
                assert "loc" not in e, "Unexpected Pydantic body validation error"


@pytest.mark.asyncio
async def test_export_invalid_format_rejected(test_app: FastAPI):
    """Sending an unknown format value should return 422."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "export-badfmt-001"
        await _seed_course(client, course_id=cid)

        r = await client.post(f"/api/v1/export/scorm/{cid}?format=xapi_v3")
        # FastAPI validates Literal on query params → 422
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_export_tabs_preserves_structured_data_and_player_support(test_app: FastAPI):
    """Tabs export must keep data.tabs and generated player must include tabs renderer."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        cid = "export-tabs-001"
        await _seed_course(client, course_id=cid, title="Tabs Export")

        page = await _seed_page(client, course_id=cid, page_title="Tabs Page")
        page_id = page["pageId"]

        add_tabs = await client.post(
            f"/api/v1/courses/{cid}/pages/{page_id}/components",
            json={
                "componentType": "tabs",
                "order": 0,
                "data": {
                    "tabs": [
                        {"id": "t1", "title": "Overview", "body": "Welcome"},
                        {"id": "t2", "title": "Details", "body": "More info"},
                    ]
                },
            },
        )
        assert add_tabs.status_code in (200, 201), add_tabs.text

        export_resp = await client.post(f"/api/v1/export/scorm/{cid}?format=scorm_1_2")
        assert export_resp.status_code == 200, export_resp.text

        zf = zipfile.ZipFile(io.BytesIO(export_resp.content))

        js_candidates = [n for n in zf.namelist() if n.endswith("course_data.js")]
        assert js_candidates, f"No course_data.js found: {zf.namelist()}"
        js_content = zf.read(js_candidates[0]).decode("utf-8")

        match = re.search(r"var courseData\s*=\s*(\{.*?\});", js_content, re.DOTALL)
        assert match, "Could not parse courseData object from course_data.js"
        course_data = json.loads(match.group(1))

        templates = course_data.get("templates", [])
        tabs_slides = [t for t in templates if t.get("type") == "tabs"]
        assert tabs_slides, f"Expected tabs slide in templates, got: {templates}"
        assert isinstance(tabs_slides[0].get("data", {}).get("tabs"), list)
        assert len(tabs_slides[0]["data"]["tabs"]) == 2

        html_candidates = [n for n in zf.namelist() if n.endswith("index.html")]
        assert html_candidates, "No index.html found in export"
        html_content = zf.read(html_candidates[0]).decode("utf-8")
        assert "renderTabs" in html_content
        assert "slide.type === 'tabs'" in html_content
