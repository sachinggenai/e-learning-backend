"""AI session context model.

TODO(SESSION): When real session infrastructure is built, this will
be persisted in Redis with TTL and distributed session validation.

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR04_enriched.md
"""

from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, Field


class SessionContext(BaseModel):
    """AI authoring session context.

    Sessions are scoped to a single course for a single user within
    one organization. The course_id is immutable for the session lifetime.

    TODO(SESSION): Add created_at, last_accessed_at, ip_address,
    user_agent for real session management with Redis persistence.
    """

    session_id: str = Field(description="Unique session identifier (UUID v4)")
    user_id: str = Field(description="UUID of the session owner")
    organization_id: str = Field(description="UUID of the user's organization")
    course_id: str = Field(
        description="UUID of the course being authored (immutable for session lifetime)"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Session creation timestamp (UTC)",
    )
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(hours=24),
        description="Session expiry timestamp (UTC). Default: 24 hours.",
    )

    def is_expired(self) -> bool:
        """Check if the session has expired."""
        return datetime.utcnow() > self.expires_at

    def minutes_remaining(self) -> float:
        """Return minutes until session expiry."""
        remaining = (self.expires_at - datetime.utcnow()).total_seconds() / 60.0
        return max(0.0, remaining)

    class Config:
        arbitrary_types_allowed = True
