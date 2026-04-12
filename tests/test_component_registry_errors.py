import os
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from app.main import app as real_app
from app.db.config import get_session
from app.models.base import Base
import app.models.component_type  # noqa: F401

TEST_DB_URL = "sqlite+aiosqlite:///./test_component_registry_errors.db"

if os.path.exists("test_component_registry_errors.db"):
    os.remove("test_component_registry_errors.db")


@pytest.fixture(scope="module")
async def test_app() -> FastAPI:
    engine = create_async_engine(TEST_DB_URL, future=True, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_session():
        async with session_factory() as session:
            yield session

    real_app.dependency_overrides[get_session] = _override_session
    yield real_app

    real_app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_components_list_returns_controlled_500_with_cors(test_app: FastAPI, monkeypatch):
    from app.repositories.component_type_repo import ComponentTypeRepository

    async def _boom(*args, **kwargs):
        raise RuntimeError("db is down")

    monkeypatch.setattr(ComponentTypeRepository, "list", _boom)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/components?page=1&limit=10",
            headers={"Origin": "http://localhost:3000"},
        )

    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    body = resp.json()
    assert body["detail"]["errors"][0]["code"] == "COMPONENT_REGISTRY_LIST_FAILED"


@pytest.mark.asyncio
async def test_components_categories_returns_controlled_500_with_cors(test_app: FastAPI, monkeypatch):
    from app.repositories.component_type_repo import ComponentTypeRepository

    async def _boom(*args, **kwargs):
        raise RuntimeError("db is down")

    monkeypatch.setattr(ComponentTypeRepository, "get_categories", _boom)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/components/categories",
            headers={"Origin": "http://localhost:3000"},
        )

    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    body = resp.json()
    assert body["detail"]["errors"][0]["code"] == "COMPONENT_REGISTRY_CATEGORIES_FAILED"
