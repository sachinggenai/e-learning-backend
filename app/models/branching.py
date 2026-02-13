"""Branching & Adaptive Navigation ORM models.

Supports branching rules, conditions, and learner branch-path tracking
for scenario and diagnostic templates.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Integer, Boolean, ForeignKey

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class BranchRule(Base):
    """A branching rule attached to a course.

    Defines conditions under which a learner is routed to a different
    page/component path rather than the default linear sequence.
    """

    __tablename__ = "branch_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    branch_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("courses.course_id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # The page/component from which branching originates
    source_page_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_component_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # JSON array of condition objects:
    # [{"field": "score", "operator": ">=", "value": 80, "targetPageId": "page-3"}, ...]
    conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Fallback target when no condition matches
    default_target_page_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Priority for evaluation ordering (lower = evaluated first)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "branchId": self.branch_id,
            "courseId": self.course_id,
            "title": self.title,
            "description": self.description,
            "sourcePageId": self.source_page_id,
            "sourceComponentId": self.source_component_id,
            "conditions": self.conditions,
            "defaultTargetPageId": self.default_target_page_id,
            "priority": self.priority,
            "isActive": self.is_active,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class BranchEvent(Base):
    """Records a learner's branch decision for reporting/resume.

    Each row tracks which branch path was taken at a given decision point.
    """

    __tablename__ = "branch_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    branch_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("branch_rules.branch_id", ondelete="CASCADE"),
        index=True,
    )
    course_id: Mapped[str] = mapped_column(String(64), index=True)
    learner_id: Mapped[str] = mapped_column(String(128), index=True, default="anonymous")

    # Which condition index matched (-1 for default)
    matched_condition_index: Mapped[int] = mapped_column(Integer, default=-1)
    target_page_id: Mapped[str] = mapped_column(String(64))

    # Snapshot of evaluation context (score, responses, etc.)
    context_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "branchId": self.branch_id,
            "courseId": self.course_id,
            "learnerId": self.learner_id,
            "matchedConditionIndex": self.matched_condition_index,
            "targetPageId": self.target_page_id,
            "contextSnapshot": self.context_snapshot,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
