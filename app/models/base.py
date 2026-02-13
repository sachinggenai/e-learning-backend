"""Unified SQLAlchemy declarative base for all ORM models.

All ORM model files MUST import Base from this module to ensure
a single metadata registry, enabling cross-table ForeignKeys and
correct Alembic autogenerate behavior.
"""
from sqlalchemy.orm import declarative_base

Base = declarative_base()
