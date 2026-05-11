"""Database configuration and session management.

Provides an async SQLAlchemy engine + session factory for PostgreSQL.

Environment Variables:
    DATABASE_URL: Full database URL (postgresql+asyncpg://user:pass@host:5432/dbname)
    POSTGRES_USER: PostgreSQL username (default: postgres)
    POSTGRES_PASSWORD: PostgreSQL password (default: postgres)
    POSTGRES_HOST: PostgreSQL host (default: localhost)
    POSTGRES_PORT: PostgreSQL port (default: 5432)
    POSTGRES_DB: PostgreSQL database name (default: elearning)
    SQL_ECHO: Enable SQL query logging (default: false)
    DB_POOL_SIZE: Connection pool size (default: 10)
    DB_MAX_OVERFLOW: Max overflow connections (default: 20)
"""
from __future__ import annotations
import os
from typing import AsyncGenerator
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)

load_dotenv()

# Build PostgreSQL URL from environment variables if not explicitly set


def get_database_url() -> str:
    """Get database URL from environment or construct from components."""
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"]
    
    # Construct PostgreSQL URL from components
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_password = os.getenv("POSTGRES_PASSWORD", "postgres")
    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB", "elearning")
    
    return (
        f"postgresql+asyncpg://{pg_user}:{pg_password}"
        f"@{pg_host}:{pg_port}/{pg_db}"
    )


DATABASE_URL = get_database_url()

# Engine configuration with PostgreSQL connection pooling
engine_kwargs = {
    "echo": os.getenv("SQL_ECHO", "false").lower() == "true",
    "future": True,
    "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
    "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
    "pool_pre_ping": True,
    "pool_recycle": 3600,  # Recycle connections after 1 hour
}

engine = create_async_engine(DATABASE_URL, **engine_kwargs)

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
