"""Repository for AIConfirmationTokenRecord — confirmation token persistence.

Follows the standard repository pattern (AsyncSession constructor,
Optional return for not-found, explicit commit+refresh).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIConfirmationTokenRecord


class AIConfirmationTokenRepository:
    """Data access for ai_confirmation_tokens table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, token_id: str) -> Optional[AIConfirmationTokenRecord]:
        """Get a confirmation token by its string UUID."""
        q = select(AIConfirmationTokenRecord).where(
            AIConfirmationTokenRecord.token_id == token_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_by_proposal(
        self, proposal_id: str
    ) -> Optional[AIConfirmationTokenRecord]:
        """Get the confirmation token bound to a proposal."""
        q = select(AIConfirmationTokenRecord).where(
            AIConfirmationTokenRecord.proposal_id == proposal_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_valid(
        self, token_id: str
    ) -> Optional[AIConfirmationTokenRecord]:
        """Get a token that is still valid (not consumed, not expired)."""
        now = datetime.utcnow()
        q = select(AIConfirmationTokenRecord).where(
            AIConfirmationTokenRecord.token_id == token_id,
            AIConfirmationTokenRecord.is_confirmed == False,  # noqa: E712
            AIConfirmationTokenRecord.expires_at > now,
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(
        self, record: AIConfirmationTokenRecord
    ) -> AIConfirmationTokenRecord:
        """Insert a new confirmation token."""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update(
        self, record: AIConfirmationTokenRecord
    ) -> AIConfirmationTokenRecord:
        """Persist changes to an existing token record."""
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def consume(self, token_id: str) -> Optional[AIConfirmationTokenRecord]:
        """Consume a token (mark as confirmed). Returns None if not found."""
        record = await self.get(token_id)
        if record is None:
            return None
        record.is_confirmed = True
        record.confirmed_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(record)
        return record
