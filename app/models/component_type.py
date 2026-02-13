"""Component Type ORM model — the Component Type Registry.

Replaces/extends `template_types` with richer metadata:
scoring config, audio support, completion capabilities, JSON Schema, etc.
Seeded at startup (see app/services/seed_component_types.py).
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Integer, Boolean, Float

from app.models.base import Base


class ComponentType(Base):
    """Registry entry describing one component type (e.g. 'tabs', 'mcq')."""

    __tablename__ = "component_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Unique slug — used as the value of Component.componentType
    type_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    # UI presentation
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(100), default="component")
    thumbnail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Category grouping
    category: Mapped[str] = mapped_column(String(100), index=True)

    # Capabilities
    scoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scoring_rules: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Completion types this component can satisfy
    completion_capabilities: Mapped[list] = mapped_column(
        JSON, default=list
    )  # e.g. ["view", "interact", "audio", "score"]
    default_completion_type: Mapped[str] = mapped_column(
        String(50), default="view"
    )

    # Audio support
    audio_support: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: {"perComponent": False, "perInteraction": False, "interactionPoints": None},
    )

    # JSON Schema for validating component data
    schema: Mapped[dict] = mapped_column(JSON, default=dict)

    # Default data when a new component of this type is created
    default_data: Mapped[dict] = mapped_column(JSON, default=dict)

    # Tags for search / filtering
    tags: Mapped[list] = mapped_column(JSON, default=list)

    # Ordering & state
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    estimated_duration: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self, full: bool = False) -> dict:
        """Return summary dict; if full=True include schema & defaults."""
        d = {
            "typeId": self.type_id,
            "category": self.category,
            "displayName": self.display_name,
            "description": self.description,
            "icon": self.icon,
            "thumbnail": self.thumbnail,
            "completionCapabilities": self.completion_capabilities or [],
            "scoringEnabled": self.scoring_enabled,
            "audioSupport": self.audio_support or {},
            "tags": self.tags or [],
            "estimatedDuration": self.estimated_duration,
        }
        if full:
            d.update(
                {
                    "schema": self.schema,
                    "defaultData": self.default_data,
                    "defaultCompletionType": self.default_completion_type,
                    "maxScore": self.max_score,
                    "scoringRules": self.scoring_rules,
                    "sortOrder": self.sort_order,
                    "isActive": self.is_active,
                    "createdAt": self.created_at.isoformat() if self.created_at else None,
                    "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
                }
            )
        return d
