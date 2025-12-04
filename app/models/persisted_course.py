"""SQLAlchemy ORM models for persisted entities (Phase 2 foundations).

Separate from Pydantic models in course.py which describe in-memory validation
for import/export. This layer manages persistence concerns only.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column, declarative_base
from sqlalchemy import (
    String,
    DateTime,
    JSON,
    Text,
    ForeignKey,
    Integer,
    Boolean,
    Float,
)

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
    schema_signature: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
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
            "schemaSignature": self.schema_signature,
            "title": self.title,
            "order": self.order_index,
            "data": self.json_data,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }


class TemplateDefinition(Base):
    """Dynamic template definitions for rendering SCORM content.

    Stores HTML templates, schema definitions, and metadata for template types.
    Used by the dynamic rendering system in Phase 3.
    """
    __tablename__ = "template_definitions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_type: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    schema_signature: Mapped[str] = mapped_column(String(64), index=True)  # SHA256 hash
    render_template_html: Mapped[str] = mapped_column(Text, nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "templateType": self.template_type,
            "displayName": self.display_name,
            "schemaSignature": self.schema_signature,
            "renderTemplateHtml": self.render_template_html,
            "schemaJson": self.schema_json,
            "isActive": self.is_active,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }


class ImportJob(Base):
    """Tracks SCORM import jobs and their progress.

    Used for background processing of SCORM package imports, with status
    tracking and error reporting.
    """
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, processing, completed, failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 to 1.0
    course_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Target course ID
    source_file_path: Mapped[str] = mapped_column(String(500))  # Path to uploaded SCORM zip
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Parsed course data
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "jobId": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "courseId": self.course_id,
            "sourceFilePath": self.source_file_path,
            "errorMessage": self.error_message,
            "resultData": self.result_data,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }


class GlobalTemplate(Base):
    """Global template instances for shared content.

    Stores templates that can be referenced across multiple courses,
    with versioning and metadata.
    """
    __tablename__ = "global_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    global_template_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    template_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(200))
    json_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "globalTemplateId": self.global_template_id,
            "templateType": self.template_type,
            "title": self.title,
            "data": self.json_data,
            "version": self.version,
            "isPublished": self.is_published,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
