import asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
import pytest

from app.main import app as real_app
from app.db.config import get_session
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.pool import NullPool
from app.models.persisted_course import Base as PersistedBase

TEST_DB_URL = "sqlite+aiosqlite:///./test_course_updated_at.db"


@pytest.fixture(scope="module")
async def test_app():
    # Fresh DB
    engine = create_async_engine(TEST_DB_URL, future=True, poolclass=NullPool)
    async_session = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(PersistedBase.metadata.create_all)

    async def override_session():
        async with async_session() as session:  # type: ignore
            yield session

    real_app.dependency_overrides[get_session] = override_session
    yield real_app
    real_app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_updated_at_monotonic_increase(test_app: FastAPI):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        payload = {
            "courseId": "mono1",
            "title": "Title",
            "description": None,
            "data": {},
        }
        r = await client.post("/api/v1/courses", json=payload)
        assert r.status_code == 201, r.text
        created = r.json()
        cid = created["courseId"]
        created_at = created["createdAt"]
        updated_at_initial = created["updatedAt"]
        # Ensure initial timestamps exist
        assert created_at <= updated_at_initial
        # Wait a tick
        await asyncio.sleep(0.2)
        # Patch update
        r2 = await client.patch(
            f"/api/v1/courses/{cid}", json={"title": "NewTitle"}
        )
        assert r2.status_code == 200, r2.text
        updated = r2.json()
        assert updated["updatedAt"] > updated_at_initial, (
            updated["updatedAt"],
            updated_at_initial,
        )
