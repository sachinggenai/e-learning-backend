"""AI Feedback ORM model — US-PEND-025."""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, DateTime, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class AIFeedbackRecord(Base):
    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    feedback_id: Mapped[str] = mapped_column(String(64), unique=True, default="")
    proposal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    course_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    generated_content: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    applied_content: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    edit_distance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    edit_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    template_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    time_to_decision_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
