"""
Tests for Phase 3 course API contract:
  B1: Extended fields (author, navigation, settings, scoring) on PUT/PATCH/POST
  B2: Composite GET /courses/{courseId} returns pages[] with nested components[]
"""
import os
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from app.main import app as real_app
from app.db.config import get_session
from app.models.base import Base
import app.models.persisted_course  # noqa: F401
import app.models.page_component    # noqa: F401

TEST_DB = "test_course_phase3.db"
TEST_DB_URL = f"sqlite+aiosqlite:///./{TEST_DB}"

if os.path.exists(TEST_DB):
    os.remove(TEST_DB)


@pytest.fixture(scope="module")
async def test_app():
    engine = create_async_engine(TEST_DB_URL, future=True, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override():
        async with session_factory() as session:
            yield session

    real_app.dependency_overrides[get_session] = _override
    yield real_app
    real_app.dependency_overrides.clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# B1: Extended fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_extended_fields_stored_and_returned(test_app):
    """PUT with author/navigation/scoring stores them in json_data and returns at top level."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        resp = await ac.put(
            "/api/v1/courses/phase3-ext",
            json={
                "courseId": "phase3-ext",
                "title": "Extended Test",
                "author": "Alice",
                "language": "en",
                "version": "2.0.0",
                "navigation": {"allowSkip": True, "showProgress": True},
                "settings": {"autoplay": False},
                "scoring": {"config": {"passingScore": 70}},
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["author"] == "Alice"
        assert body["language"] == "en"
        assert body["version"] == "2.0.0"
        assert body["navigation"]["allowSkip"] is True
        assert body["settings"]["autoplay"] is False
        assert body["scoring"]["config"]["passingScore"] == 70


@pytest.mark.asyncio
async def test_patch_merges_extended_fields(test_app):
    """PATCH with navigation updates it without losing existing author."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        resp = await ac.patch(
            "/api/v1/courses/phase3-ext",
            json={
                "navigation": {"allowSkip": False, "showProgress": True, "linearProgression": True},
                "scoring": {"config": {"passingScore": 80}},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Author should still be there from the PUT
        assert body["author"] == "Alice"
        # Navigation should be updated
        assert body["navigation"]["allowSkip"] is False
        assert body["navigation"]["linearProgression"] is True
        # Scoring should be updated
        assert body["scoring"]["config"]["passingScore"] == 80


@pytest.mark.asyncio
async def test_post_extended_fields(test_app):
    """POST /courses with extended fields stores and returns them."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            "/api/v1/courses",
            json={
                "courseId": "phase3-post",
                "title": "POST Extended",
                "author": "Bob",
                "navigation": {"allowSkip": True, "showProgress": False},
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["author"] == "Bob"
        assert body["navigation"]["showProgress"] is False


@pytest.mark.asyncio
async def test_get_returns_extended_fields(test_app):
    """GET /courses/{courseId} returns extended fields at top level."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/v1/courses/phase3-ext")
        assert resp.status_code == 200
        body = resp.json()
        assert body["author"] == "Alice"
        assert body["navigation"]["linearProgression"] is True


@pytest.mark.asyncio
async def test_list_returns_extended_fields(test_app):
    """GET /courses list includes extended fields."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/v1/courses")
        assert resp.status_code == 200
        items = resp.json()
        authors = [c.get("author") for c in items if c.get("author")]
        assert "Alice" in authors


# ---------------------------------------------------------------------------
# B2: Composite GET with pages + components
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_composite_get_includes_empty_pages(test_app):
    """GET course with no pages returns pages: []."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/v1/courses/phase3-post")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pages"] == []


@pytest.mark.asyncio
async def test_composite_get_includes_pages_and_components(test_app):
    """GET course returns pages[] with nested components[]."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        # Create a page with components
        page_resp = await ac.post(
            "/api/v1/courses/phase3-ext/pages",
            json={
                "title": "Test Page",
                "components": [
                    {"componentType": "welcome", "data": {"title": "Hello"}},
                    {"componentType": "mcq", "data": {"question": "Q1?", "options": []}},
                ],
            },
        )
        assert page_resp.status_code == 201

        # Now GET composite
        resp = await ac.get("/api/v1/courses/phase3-ext")
        assert resp.status_code == 200
        body = resp.json()

        assert isinstance(body["pages"], list)
        assert len(body["pages"]) >= 1

        page = body["pages"][0]
        assert "pageId" in page
        assert "title" in page
        assert isinstance(page["components"], list)
        assert len(page["components"]) == 2

        comp = page["components"][0]
        assert "componentId" in comp
        assert "componentType" in comp
        assert "data" in comp


@pytest.mark.asyncio
async def test_composite_get_pages_ordered(test_app):
    """Pages are returned in order_index order."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        # Add a second page
        await ac.post(
            "/api/v1/courses/phase3-ext/pages",
            json={"title": "Second Page"},
        )

        resp = await ac.get("/api/v1/courses/phase3-ext")
        body = resp.json()
        orders = [p["order"] for p in body["pages"]]
        assert orders == sorted(orders)
