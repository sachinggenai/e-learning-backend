"""Idempotency Service — US-BKND-AI-010.

Provides exactly-once apply semantics by storing idempotency keys and
cached responses. When the same key is retried within its TTL window,
the original response is returned without re-executing the mutation.

Uses AIIdempotencyRepository for persistence (already existed from AI-004).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIIdempotencyKeyRecord
from app.repositories.ai_idempotency_repo import AIIdempotencyRepository
from app.services.ai.config import get_ai_config

logger = logging.getLogger("ai_authoring")


class IdempotencyService:
    """Manages idempotency keys for safe retry of AI mutations.

    Usage in apply flow:
        svc = IdempotencyService(db)
        cached = await svc.check(key, user_id, session_id)
        if cached:
            return cached  # Return original response

        # Execute mutation...
        result = await do_apply(...)

        await svc.store(key, user_id, session_id, result, status=200)
        return result
    """

    def __init__(self, db: AsyncSession):
        self.repo = AIIdempotencyRepository(db)
        self.config = get_ai_config()

    async def check(
        self, idempotency_key: str, user_id: str, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Check if an idempotency key already has a cached response.

        Returns the cached response dict if found and valid, None otherwise.
        """
        if not idempotency_key:
            return None

        record = await self.repo.get_valid(idempotency_key)
        if record is None:
            return None

        # Verify ownership
        if record.user_id != user_id or record.session_id != session_id:
            logger.warning(
                "Idempotency key %s belongs to different user/session",
                idempotency_key[:8],
            )
            return None

        logger.debug("Idempotency key %s hit — returning cached response",
                      idempotency_key[:8])
        return record.response_body

    async def store(
        self,
        idempotency_key: str,
        user_id: str,
        session_id: str,
        response: Dict[str, Any],
        status: int = 200,
    ) -> None:
        """Store an idempotency record with the response.

        If the key already exists (race condition), the existing record
        is left intact (first-write-wins).
        """
        if not idempotency_key:
            return

        existing = await self.repo.get(idempotency_key)
        if existing is not None:
            logger.debug("Idempotency key %s already stored — skipping",
                          idempotency_key[:8])
            return

        ttl = self.config.idempotency_ttl_hours
        now = datetime.utcnow()
        request_hash = hashlib.sha256(
            str(response).encode("utf-8")
        ).hexdigest()[:64]

        record = AIIdempotencyKeyRecord(
            idempotency_key=idempotency_key,
            session_id=session_id,
            user_id=user_id,
            request_hash=request_hash,
            response_status=status,
            response_body=response,
            created_at=now,
            expires_at=now + timedelta(hours=ttl),
        )
        await self.repo.create(record)
        logger.debug("Idempotency key %s stored (TTL=%dh)",
                      idempotency_key[:8], ttl)

    async def cleanup_expired(self) -> int:
        """Remove expired idempotency records."""
        return await self.repo.delete_expired()

    @staticmethod
    def generate_key(proposal_id: str, user_id: str) -> str:
        """Generate a deterministic idempotency key from proposal + user."""
        raw = f"{proposal_id}:{user_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
