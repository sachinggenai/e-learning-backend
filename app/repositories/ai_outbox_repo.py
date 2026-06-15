"""Repository for AIOutboxEventRecord — outbox event persistence.

Implements the transactional outbox pattern. Events are written
in the same DB transaction as the domain mutation, then published
asynchronously by a background worker.

Follows the standard repository pattern.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIOutboxEventRecord


class AIOutboxRepository:
    """Data access for ai_outbox_events table (transactional outbox)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, record: AIOutboxEventRecord) -> AIOutboxEventRecord:
        """Insert a new outbox event."""
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def claim_pending(
        self, batch_size: int = 10
    ) -> List[AIOutboxEventRecord]:
        """Claim a batch of pending events for processing.

        Events are selected oldest-first and marked as 'processing'
        in the same query to prevent double-processing.
        """
        q = (
            select(AIOutboxEventRecord)
            .where(AIOutboxEventRecord.status == "pending")
            .order_by(AIOutboxEventRecord.created_at.asc())
            .limit(batch_size)
        )
        result = await self.session.execute(q)
        events = list(result.scalars().all())
        for ev in events:
            ev.status = "processing"
        if events:
            await self.session.commit()
        return events

    async def mark_processed(self, event_id: str) -> None:
        """Mark an event as successfully processed."""
        now = datetime.utcnow()
        q = select(AIOutboxEventRecord).where(
            AIOutboxEventRecord.event_id == event_id
        )
        ev = (await self.session.execute(q)).scalar_one_or_none()
        if ev:
            ev.status = "processed"
            ev.processed_at = now
            await self.session.commit()

    async def mark_failed(self, event_id: str, error: str) -> None:
        """Mark an event as failed and increment retry count."""
        q = select(AIOutboxEventRecord).where(
            AIOutboxEventRecord.event_id == event_id
        )
        ev = (await self.session.execute(q)).scalar_one_or_none()
        if ev:
            ev.status = "failed"
            ev.error_message = error
            ev.retry_count = (ev.retry_count or 0) + 1
            await self.session.commit()

    async def list_by_status(self, status: str) -> List[AIOutboxEventRecord]:
        """List events by status, oldest first."""
        q = (
            select(AIOutboxEventRecord)
            .where(AIOutboxEventRecord.status == status)
            .order_by(AIOutboxEventRecord.created_at.asc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get_pending_count(self) -> int:
        """Count pending events."""
        q = select(AIOutboxEventRecord).where(
            AIOutboxEventRecord.status == "pending"
        )
        result = await self.session.execute(q)
        return len(result.scalars().all())
