"""Scoring configuration ORM model — per-course scoring & completion settings."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, ForeignKey

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CourseScoringRecord(Base):
    """Scoring configuration for a course."""

    __tablename__ = "course_scoring"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scoring_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("courses.course_id", ondelete="CASCADE"),
        unique=True, index=True,
    )

    # Scoring config (passingScore, maxAttempts, attemptScoring, etc.)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Per-component score configs
    component_scores: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # SCORM reporting config
    scorm_reporting: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "scoringId": self.scoring_id,
            "courseId": self.course_id,
            "config": self.config,
            "componentScores": self.component_scores,
            "scormReporting": self.scorm_reporting,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
