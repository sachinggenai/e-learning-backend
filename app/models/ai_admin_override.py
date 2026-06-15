"""ORM model for admin override audit trail.

US-BKND-AI-049: Records every admin bypass of the confirmation token
requirement for destructive operations, providing a complete audit
trail for compliance and security review.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, ForeignKey, DateTime

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AIAdminOverrideRecord(Base):
    """Records an admin bypass of confirmation token validation.

    Each record includes who performed the bypass, why, on which
    proposal, and from which IP. Rate-limited to 5 per admin per hour.
    """

    __tablename__ = "ai_admin_overrides"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    override_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    proposal_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_proposals.proposal_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    admin_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    overridden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "overrideId": self.override_id,
            "proposalId": self.proposal_id,
            "adminUserId": self.admin_user_id,
            "reason": self.reason,
            "overriddenAt": (
                self.overridden_at.isoformat() if self.overridden_at else None
            ),
            "sessionId": self.session_id,
            "ipAddress": self.ip_address,
            "userAgent": self.user_agent,
        }
