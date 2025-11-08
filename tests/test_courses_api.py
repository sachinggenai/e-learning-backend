import os
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.pool import NullPool

from app.main import app as real_app
from app.db.config import get_session
from app.models.persisted_course import Base as PersistedBase

TEST_DB_URL = "sqlite+aiosqlite:///./test_courses.db"

# Ensure fresh DB file for test module
if os.path.exists("test_courses.db"):
    os.remove("test_courses.db")
 
 
@pytest.fixture(scope="module")
async def test_app():
    # Create isolated in-memory engine
    engine = create_async_engine(TEST_DB_URL, future=True, poolclass=NullPool)
    async_session = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create schema
    async with engine.begin() as conn:
        await conn.run_sync(PersistedBase.metadata.create_all)

    # Dependency override
    async def override_session():
        async with async_session() as session:  # type: ignore
            yield session

    real_app.dependency_overrides[get_session] = override_session

    yield real_app

    # Teardown
    real_app.dependency_overrides.clear()
    await engine.dispose()

 
@pytest.mark.asyncio
async def test_course_crud_flow(test_app: FastAPI):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        # Create
        payload = {
            "courseId": "c1",
            "title": "Title",
            "description": "Desc",
            "data": {"templates": []},
        }
        r = await client.post("/api/v1/courses", json=payload)
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["courseId"] == "c1"

        # List
        r = await client.get("/api/v1/courses")
        assert r.status_code == 200
        lst = r.json()
        assert len(lst) == 1

        cid = created["courseId"]
        # Get
        r = await client.get(f"/api/v1/courses/{cid}")
        assert r.status_code == 200

        # Patch
        r = await client.patch(f"/api/v1/courses/{cid}", json={"title": "New"})
        assert r.status_code == 200
        assert r.json()["title"] == "New"

        # Delete
        r = await client.delete(f"/api/v1/courses/{cid}")
        assert r.status_code == 204

        # Confirm gone
        r = await client.get(f"/api/v1/courses/{cid}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_course_duplicate_id(test_app: FastAPI):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        payload = {
            "courseId": "dup1",
            "title": "Course One",
            "description": None,
            "data": {},
        }
        r = await client.post("/api/v1/courses", json=payload)
        assert r.status_code == 201

        # Attempt duplicate
        r = await client.post("/api/v1/courses", json=payload)
        assert r.status_code == 400
        body = r.json()
        assert (
            body.get("detail") == "courseId already exists"
            or body.get("error") == "courseId already exists"
        )
