"""Interaction Event ORM model — persists interaction events for reporting.

Stores fine-grained interaction events (flip, reveal, drag-sort, text-input,
rating, acknowledge, download, etc.) beyond the in-memory approach in
scoring_completion router.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Float, Boolean, ForeignKey

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class InteractionEventRecord(Base):
    """Persisted interaction event for reporting and resume."""

    __tablename__ = "interaction_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("courses.course_id", ondelete="CASCADE"),
        index=True,
    )
    page_id: Mapped[str] = mapped_column(String(64), index=True)
    component_id: Mapped[str] = mapped_column(String(64), index=True)
    learner_id: Mapped[str] = mapped_column(String(128), index=True, default="anonymous")

    # Open string — NOT a closed enum.  Accepts any type the frontend sends
    # (flip, reveal, drag-sort, text-input, rating, acknowledge, download, …).
    interaction_type: Mapped[str] = mapped_column(String(100), index=True)

    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "courseId": self.course_id,
            "pageId": self.page_id,
            "componentId": self.component_id,
            "learnerId": self.learner_id,
            "interactionType": self.interaction_type,
            "data": self.data,
            "completed": self.completed,
            "score": self.score,
            "maxScore": self.max_score,
            "duration": self.duration,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
