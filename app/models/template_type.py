"""Template Type ORM Model for builtin/reusable template definitions.

Stores template types that can be used across courses (e.g., introduction, lab,
assessment). These are the "template types" shown in the template picker UI,
not individual course templates.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Float, Integer, Boolean

from app.models.base import Base


class TemplateType(Base):
    """Builtin/reusable template type definition.
    
    Represents a template type that can be instantiated in courses.
    Examples: introduction, lab, assessment, content, video, etc.
    """
    __tablename__ = "template_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Unique identifier for the template type
    template_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True
    )

    # Display name and description
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)

    # Category for UI organization
    category: Mapped[str] = mapped_column(String(100), index=True)

    # UI presentation
    thumbnail: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )

    # Metadata
    estimated_duration: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # minutes
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    # Can this template be used as a page?
    can_be_page: Mapped[bool] = mapped_column(Boolean, default=True)

    # Field definitions (JSON schema)
    fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Whether this template is active/available for use
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def to_dict(self) -> dict:
        """Convert to dictionary format for API responses."""
        return {
            "id": self.id,
            "templateId": self.template_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "thumbnail": self.thumbnail,
            "estimated_duration": self.estimated_duration,
            "rating": self.rating,
            "usage_count": self.usage_count,
            "can_be_page": self.can_be_page,
            "fields": self.fields,
            "is_active": self.is_active,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
