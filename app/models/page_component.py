"""Page and Component ORM models — the composable page→component hierarchy.

Replaces the in-memory COURSE_PAGES dict and enables multi-component pages.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, DateTime, JSON, Text, Integer, Boolean, ForeignKey

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class PageRecord(Base):
    """A page within a course — ordered container of components."""

    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("courses.course_id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    # Layout system (preset + custom grid + placements)
    layout: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Page-level theme override config
    theme_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Page completion config
    completion_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    components: Mapped[list["ComponentRecord"]] = relationship(
        "ComponentRecord",
        back_populates="page",
        cascade="all, delete-orphan",
        order_by="ComponentRecord.order_index",
        lazy="selectin",
    )

    def to_dict(self, include_components: bool = True) -> dict:
        d = {
            "pageId": self.page_id,
            "title": self.title,
            "order": self.order_index,
            "layout": self.layout,
            "theme": self.theme_config,
            "pageCompletion": self.completion_config,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_components:
            d["components"] = [c.to_dict() for c in (self.components or [])]
        return d


class ComponentRecord(Base):
    """A single component on a page — one content/interactive element."""

    __tablename__ = "components"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    component_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    page_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("pages.page_id", ondelete="CASCADE"), index=True
    )
    component_type: Mapped[str] = mapped_column(String(100), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    # Component-specific data (validated against ComponentType.schema)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Audio configuration
    audio_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Completion criteria
    completion_criteria: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Styling / theme overrides
    styling: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    page: Mapped["PageRecord"] = relationship(
        "PageRecord", back_populates="components"
    )

    def to_dict(self) -> dict:
        return {
            "componentId": self.component_id,
            "componentType": self.component_type,
            "order": self.order_index,
            "data": self.data,
            "audioConfig": self.audio_config,
            "completionCriteria": self.completion_criteria,
            "styling": self.styling,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
