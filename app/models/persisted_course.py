"""SQLAlchemy ORM models for persisted entities (Phase 2 foundations).

Separate from Pydantic models in course.py which describe in-memory validation
for import/export. This layer manages persistence concerns only.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column, declarative_base
from sqlalchemy import String, DateTime, JSON, Text, ForeignKey

Base = declarative_base()


class CourseRecord(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    json_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "courseId": self.course_id,
            "title": self.title,
            "status": self.status,
            "description": self.description,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "data": self.json_data,
        }


class TemplateRecord(Base):
    """Normalized template/page entity related to a course.

    This allows querying, indexing, and future granular operations (e.g.,
    per-template versioning, analytics) independent of full course JSON.
    """

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    template_uid: Mapped[str] = mapped_column(String(100), index=True)
    template_type: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    order_index: Mapped[int] = mapped_column()
    json_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "courseId": self.course_id,
            "templateId": self.template_uid,
            "type": self.template_type,
            "title": self.title,
            "order": self.order_index,
            "data": self.json_data,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
