"""Theme ORM model — design system themes (colors, typography, component styles).

Supports preset (built-in) and custom themes. Applied at course or page level
with cascading overrides.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Boolean

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ThemeRecord(Base):
    """A theme with colors, typography, and component styles."""

    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    theme_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    name: Mapped[str] = mapped_column(String(200))
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)

    # Full theme definition
    colors: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    typography: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    component_styles: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "themeId": self.theme_id,
            "name": self.name,
            "isPreset": self.is_preset,
            "colors": self.colors,
            "typography": self.typography,
            "componentStyles": self.component_styles,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
