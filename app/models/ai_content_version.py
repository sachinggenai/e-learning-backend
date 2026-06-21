"""Content versioning ORM model — US-PEND-029."""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class AIContentVersion(Base):
    __tablename__ = "ai_content_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str] = mapped_column(String(64), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    content_snapshot: Mapped[dict] = mapped_column(JSON, nullable=True)
    content_diff: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
