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

TEST_DB_URL = "sqlite+aiosqlite:///./test_templates.db"
if os.path.exists("test_templates.db"):
    os.remove("test_templates.db")


@pytest.fixture(scope="module")
async def test_app():
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
async def test_template_crud_and_reorder(test_app: FastAPI):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        # Create a course first
        course_payload = {
            "courseId": "tpl-course",
            "title": "Templates Course",
            "description": "With templates",
            "data": {"templates": []},
        }
        rc = await client.post("/api/v1/courses", json=course_payload)
        assert rc.status_code == 201, rc.text
        course = rc.json()
        cid = course["id"]

        # Add two templates
        t1 = {
            "templateId": "welcome1",
            "type": "welcome",
            "title": "Welcome 1",
            "data": {"content": "Hi"},
        }
        r1 = await client.post(f"/api/v1/courses/{cid}/templates", json=t1)
        assert r1.status_code == 201, r1.text

        t2 = {
            "templateId": "content1",
            "type": "content-text",
            "title": "Content 1",
            "data": {"content": "Body"},
        }
        r2 = await client.post(f"/api/v1/courses/{cid}/templates", json=t2)
        assert r2.status_code == 201, r2.text

        # List templates
        lst = await client.get(f"/api/v1/courses/{cid}/templates")
        assert lst.status_code == 200
        templates = lst.json()
        assert len(templates) == 2
        ids = [templates[0]["id"], templates[1]["id"]]

        # Reorder (swap)
        reorder_payload = {"orderedIds": list(reversed(ids))}
        rr = await client.post(
            f"/api/v1/courses/{cid}/templates/reorder", json=reorder_payload
        )
        assert rr.status_code == 200
        reordered = rr.json()
        assert reordered[0]["id"] == ids[1]
        assert reordered[1]["id"] == ids[0]

        # Update template
        upd = await client.patch(
            f"/api/v1/courses/{cid}/templates/{ids[0]}",
            json={"title": "Updated Title"},
        )
        assert upd.status_code == 200
        assert upd.json()["title"] == "Updated Title"

        # Verify course JSON snapshot reflects order & update
        rc2 = await client.get(f"/api/v1/courses/{cid}")
        assert rc2.status_code == 200
        course_after = rc2.json()
        snapshot = course_after["data"]["templates"]
        assert len(snapshot) == 2
        assert snapshot[0]["id"] in {"welcome1", "content1"}

        # Delete one template
        delr = await client.delete(
            f"/api/v1/courses/{cid}/templates/{ids[1]}"
        )
        assert delr.status_code == 204

        # Confirm list size decreases & snapshot sync
        lst2 = await client.get(f"/api/v1/courses/{cid}/templates")
        assert lst2.status_code == 200
        assert len(lst2.json()) == 1
        rc3 = await client.get(f"/api/v1/courses/{cid}")
        assert rc3.status_code == 200
        assert len(rc3.json()["data"]["templates"]) == 1
