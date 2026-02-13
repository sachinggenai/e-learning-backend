"""Shared test fixtures for the e-learning backend test suite.

Provides:
  - test_client: sync FastAPI TestClient backed by an in-memory SQLite DB
  - sample_course_json / sample_course_data: minimal valid course payloads
  - async_test_app: async-ready app fixture for httpx-based tests
"""
from __future__ import annotations

import json
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from app.main import app as fastapi_app
from app.db.config import get_session

# Import all models so Base.metadata.create_all creates every table
import app.models  # noqa: F401
from app.models.base import Base


# ── In-memory SQLite engine (fast, isolated per session) ─────────────────────

# Use a temp-file SQLite to avoid StaticPool threading deadlocks while
# still keeping the DB fast and isolated per test session.
import tempfile as _tmpmod
_db_file = _tmpmod.NamedTemporaryFile(suffix=".db", delete=False)
_db_file.close()
TEST_DB_URL = f"sqlite+aiosqlite:///{_db_file.name}"

_engine = create_async_engine(
    TEST_DB_URL,
    future=True,
    connect_args={"check_same_thread": False},
)

_async_session = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """Create all DB tables once before the test session starts."""
    import asyncio

    async def _setup():
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())


@pytest.fixture(scope="session", autouse=True)
def _override_session(_create_tables):
    """Override the get_session dependency with our test session for the
    entire test session lifetime."""

    async def _test_session():
        async with _async_session() as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = _test_session
    yield
    fastapi_app.dependency_overrides.clear()
    # Clean up temp DB file
    try:
        os.unlink(_db_file.name)
    except OSError:
        pass


@pytest.fixture()
def test_client(_override_session) -> TestClient:
    """Synchronous FastAPI TestClient for use with sync test functions."""
    with TestClient(fastapi_app) as client:
        yield client


@pytest.fixture()
def sample_course_data() -> dict:
    """Minimal valid course payload (dict)."""
    return {
        "courseId": "json-course-001",
        "title": "JSON Test Course",
        "author": "Test Author",
        "description": "A fixture course for automated testing",
        "templates": [
            {
                "id": "intro-page-001",
                "type": "content-text",
                "order": 0,
                "title": "Intro Page",
                "data": {"content": "<p>Hello world</p>"},
            }
        ],
    }


@pytest.fixture()
def sample_course_json(sample_course_data: dict) -> str:
    """Minimal valid course as a JSON string (for /export endpoint)."""
    return json.dumps(sample_course_data)
