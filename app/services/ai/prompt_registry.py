"""Prompt registry with versioning and A/B testing — US-PEND-028.

Manages versioned system prompts with deterministic A/B test routing.
Uses SHA-256 (not MD5) for FIPS compliance. Validates traffic splits
to prevent exceeding 100%.

Usage:
    registry = PromptRegistry(db_session)
    prompt = await registry.get_prompt("chat_response", user_id="user-123")
"""
from __future__ import annotations

import hashlib
import logging
from typing import Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_prompt_version import AIPromptVersion

logger = logging.getLogger(__name__)


class PromptRegistry:
    """Manages versioned system prompts with A/B test routing."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_prompt(self, prompt_id: str, user_id: str = "") -> str:
        stmt = (
            select(AIPromptVersion)
            .where(
                AIPromptVersion.prompt_id == prompt_id,
                AIPromptVersion.is_active == True,  # noqa: E712
            )
            .order_by(AIPromptVersion.version.desc())
        )
        result = await self.db.execute(stmt)
        variants = result.scalars().all()

        if not variants:
            return ""

        if len(variants) == 1 or variants[0].traffic_pct >= 100.0:
            return variants[0].prompt_text

        bucket = self._get_user_bucket(user_id, prompt_id)
        cumulative = 0.0
        for variant in variants:
            cumulative += variant.traffic_pct
            if bucket < cumulative:
                return variant.prompt_text

        return variants[0].prompt_text

    async def create_version(
        self, prompt_id, prompt_text, description="", author="",
        traffic_pct=100.0, ab_test_group="",
    ) -> AIPromptVersion:
        await self._validate_traffic_split(prompt_id, traffic_pct)
        stmt = (
            select(func.max(AIPromptVersion.version))
            .where(AIPromptVersion.prompt_id == prompt_id)
        )
        result = await self.db.execute(stmt)
        max_ver = result.scalar() or 0

        record = AIPromptVersion(
            prompt_id=prompt_id, version=max_ver + 1,
            prompt_text=prompt_text, description=description,
            author=author, traffic_pct=traffic_pct,
            ab_test_group=ab_test_group,
        )
        self.db.add(record)
        await self.db.commit()
        return record

    async def _validate_traffic_split(self, prompt_id, new_pct):
        stmt = (
            select(func.sum(AIPromptVersion.traffic_pct))
            .where(AIPromptVersion.prompt_id == prompt_id, AIPromptVersion.is_active == True)
        )
        result = await self.db.execute(stmt)
        current = result.scalar() or 0.0
        if current + new_pct > 100.0:
            raise ValueError(
                f"Traffic split exceeds 100%: current={current}% + new={new_pct}%"
            )

    @staticmethod
    def _get_user_bucket(user_id: str, prompt_id: str) -> float:
        seed = f"{prompt_id}:{user_id}"
        hash_val = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
        return hash_val % 100
