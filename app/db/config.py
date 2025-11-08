"""Database configuration and session management for Phase 2 foundations.

Provides an async SQLAlchemy engine + session factory. Uses ``DATABASE_URL``
environment variable with a sensible default for local development (SQLite
file) so initial setup does not block developers who haven't started Postgres
yet. When a Postgres URL is supplied (e.g.
``postgresql+asyncpg://user:pass@host:5432/dbname``) it will be used.
"""
from __future__ import annotations
import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)

# Fall back to SQLite for bootstrap if no Postgres URL supplied
# Use absolute path to ensure consistent database location
import pathlib
backend_dir = pathlib.Path(__file__).parent.parent.parent
db_path = backend_dir / "dev.db"
DEFAULT_SQLITE_URL = f"sqlite+aiosqlite:///{db_path}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

# Engine & session factory
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    future=True,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with SessionLocal() as session:  # type: ignore
        try:
            yield session
        finally:
            # rollback if something left open
            if session.in_transaction():  # defensive
                await session.rollback()
