"""Repository for AIIdempotencyKeyRecord — idempotency key persistence.

Follows the standard repository pattern (AsyncSession constructor,
Optional return for not-found, explicit commit+refresh).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIIdempotencyKeyRecord


class AIIdempotencyRepository:
    """Data access for ai_idempotency_keys table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self, idempotency_key: str
    ) -> Optional[AIIdempotencyKeyRecord]:
        """Get an idempotency record by key. Returns None if not found."""
        q = select(AIIdempotencyKeyRecord).where(
            AIIdempotencyKeyRecord.idempotency_key == idempotency_key
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_valid(
        self, idempotency_key: str
    ) -> Optional[AIIdempotencyKeyRecord]:
        """Get a non-expired idempotency record by key."""
        now = datetime.utcnow()
        q = select(AIIdempotencyKeyRecord).where(
            AIIdempotencyKeyRecord.idempotency_key == idempotency_key,
            AIIdempotencyKeyRecord.expires_at > now,
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(
        self, record: AIIdempotencyKeyRecord
    ) -> AIIdempotencyKeyRecord:
        """Insert a new idempotency record."""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def delete_expired(self) -> int:
        """Remove expired idempotency records. Returns count deleted."""
        now = datetime.utcnow()
        q = select(AIIdempotencyKeyRecord).where(
            AIIdempotencyKeyRecord.expires_at <= now
        )
        result = await self.session.execute(q)
        expired = list(result.scalars().all())
        for k in expired:
            await self.session.delete(k)
        if expired:
            await self.session.commit()
        return len(expired)
