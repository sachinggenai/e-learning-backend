"""Database configuration and setup for the e-learning platform.

This module provides SQLAlchemy setup with async SQLite support for development
and can be easily switched to PostgreSQL for production.
"""

from pathlib import Path
from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker
)
from sqlalchemy.ext.declarative import declarative_base

# Database URL - using SQLite for development
DATABASE_DIR = Path(__file__).parent.parent / "data"
DATABASE_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_DIR}/elearning.db"
SYNC_DATABASE_URL = f"sqlite:///{DATABASE_DIR}/elearning.db"

# Create async engine
async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    future=True
)

# Create sync engine for migrations
sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)

# Create sessionmaker
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Create base class for models
Base = declarative_base()

# Metadata for migrations
metadata = MetaData()


async def get_async_session():
    """Dependency to get async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections."""
    await async_engine.dispose()