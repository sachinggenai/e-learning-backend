"""Outbox event service.

Implements the transactional outbox pattern for reliable event
publishing. Events are written in the same DB transaction as the
domain operation, guaranteeing at-least-once delivery.

A background worker (future US-BKND-AI-034) polls for pending
events and publishes them to the event bus.

Supported event types:
    PageCreatedByAI, PageUpdatedByAI, PageDeletedByAI,
    SessionCreated, SessionRevoked, ProposalApplied,
    CourseCreatedFromFile, BatchProposalApplied
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_outbox_repo import AIOutboxRepository
from app.models.ai_models import AIOutboxEventRecord
from app.services.ai.config import get_ai_config

logger = logging.getLogger("ai_authoring")


class AIOutboxService:
    """Transactional outbox for AI authoring events."""

    def __init__(self, db: AsyncSession):
        self.repo = AIOutboxRepository(db)
        self.config = get_ai_config()

    async def publish(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict,
    ) -> AIOutboxEventRecord:
        """Write an outbox event in the current transaction.

        The event is NOT published immediately. A background worker
        picks it up on the next poll cycle.

        Args:
            event_type: One of the supported event types.
            aggregate_type: "session", "proposal", "page", "course".
            aggregate_id: UUID of the affected aggregate.
            payload: Event-specific data (proposal IDs, page data, etc.).
        """
        now = datetime.utcnow()
        record = AIOutboxEventRecord(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        created = await self.repo.create(record)
        logger.debug(
            "Outbox event: %s aggregate=%s/%s",
            event_type, aggregate_type, aggregate_id[:8],
        )
        return created

    async def claim_pending(
        self, batch_size: int | None = None
    ) -> List[AIOutboxEventRecord]:
        """Claim a batch of pending events for publishing."""
        if batch_size is None:
            batch_size = 10  # default batch size
        return await self.repo.claim_pending(batch_size)

    async def mark_processed(self, event_id: str) -> None:
        """Mark an event as successfully published."""
        await self.repo.mark_processed(event_id)

    async def mark_failed(self, event_id: str, error: str) -> None:
        """Mark an event as failed (will be retried)."""
        await self.repo.mark_failed(event_id, error)

    async def get_pending_count(self) -> int:
        """Get count of pending outbox events."""
        return await self.repo.get_pending_count()
