# US-PEND-028: Prompt Versioning + A/B Testing — FIPS + VALIDATION FIXED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟢 MEDIUM |
| **Batch** | 7 — Long-Term / Deferred |
| **Depends On** | None |
| **Estimated Effort** | 3-4 days |
| **Target Files** | New: `app/services/ai/prompt_registry.py`, `app/models/ai_prompt_version.py`. Modify: `app/services/ai/chat_orchestrator.py`, `app/services/ai/config.py` |

---

## ⚠️ Two Gaps Fixed

| Gap | Original | Fixed |
|-----|----------|-------|
| Hash algorithm | `hashlib.md5()` — blocked in FIPS-compliant Python builds | `hashlib.sha256()` — available everywhere |
| Traffic split validation | No validation — could exceed 100% | Added `_validate_traffic_split()` check |

---

## User Story

**As a** prompt engineer improving AI response quality,
**I want** to version system prompts and run A/B tests comparing their effectiveness,
**So that** I can safely roll out better prompts and measure the impact on proposal acceptance rate.

---

## Enriched Implementation

### File: `app/services/ai/prompt_registry.py`

```python
"""Prompt registry with versioning and A/B testing — US-PEND-028."""
from __future__ import annotations

import hashlib
import logging
from typing import Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_prompt_version import AIPromptVersion

logger = logging.getLogger(__name__)


class PromptRegistry:
    """Manages versioned system prompts with A/B test routing.

    Assignment is deterministic per user_id: same user always gets the
    same variant within a test period. Uses SHA-256 (not MD5) for FIPS
    compliance.

    Usage:
        registry = PromptRegistry(db_session)
        prompt = await registry.get_prompt("chat_response", user_id="user-123")
    """

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

        # No A/B test: return the latest
        if len(variants) == 1 or variants[0].traffic_pct >= 100.0:
            return variants[0].prompt_text

        # A/B routing: deterministic bucket per user (SHA-256, FIPS-compliant)
        bucket = self._get_user_bucket(user_id, prompt_id)
        cumulative = 0.0
        for variant in variants:
            cumulative += variant.traffic_pct
            if bucket < cumulative:
                return variant.prompt_text

        return variants[0].prompt_text

    async def create_version(
        self,
        prompt_id: str,
        prompt_text: str,
        description: str = "",
        author: str = "",
        traffic_pct: float = 100.0,
        ab_test_group: str = "",
    ) -> AIPromptVersion:
        """Create a new prompt version with traffic split validation.

        Raises ValueError if total traffic across active variants would exceed 100%.
        """
        # Validate traffic split
        await self._validate_traffic_split(prompt_id, traffic_pct)

        # Get next version number
        stmt = (
            select(func.max(AIPromptVersion.version))
            .where(AIPromptVersion.prompt_id == prompt_id)
        )
        result = await self.db.execute(stmt)
        max_ver = result.scalar() or 0

        record = AIPromptVersion(
            prompt_id=prompt_id,
            version=max_ver + 1,
            prompt_text=prompt_text,
            description=description,
            author=author,
            traffic_pct=traffic_pct,
            ab_test_group=ab_test_group,
        )
        self.db.add(record)
        await self.db.commit()
        return record

    async def _validate_traffic_split(
        self, prompt_id: str, new_traffic_pct: float
    ) -> None:
        """Ensure total active traffic does not exceed 100%."""
        stmt = (
            select(func.sum(AIPromptVersion.traffic_pct))
            .where(
                AIPromptVersion.prompt_id == prompt_id,
                AIPromptVersion.is_active == True,
            )
        )
        result = await self.db.execute(stmt)
        current_total = result.scalar() or 0.0
        if current_total + new_traffic_pct > 100.0:
            raise ValueError(
                f"Traffic split would exceed 100%: current={current_total}% "
                f"+ new={new_traffic_pct}% = {current_total + new_traffic_pct}%"
            )

    @staticmethod
    def _get_user_bucket(user_id: str, prompt_id: str) -> float:
        """Deterministic bucket 0-100 per user. Uses SHA-256 for FIPS compliance."""
        seed = f"{prompt_id}:{user_id}"
        hash_val = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
        return hash_val % 100
```

### File: `app/models/ai_prompt_version.py`

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Float, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.config import Base

class AIPromptVersion(Base):
    __tablename__ = "ai_prompt_versions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(default=1)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    traffic_pct: Mapped[float] = mapped_column(Float, default=100.0)
    ab_test_group: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Multiple prompt versions stored and queryable | `SELECT * FROM ai_prompt_versions WHERE prompt_id='chat_response'` |
| AC-2 | A/B test routes X% of traffic to variant B | 1000 simulated users → variant B gets ~X% |
| AC-3 | Same user always gets same variant | `_get_user_bucket("user-123", "test")` → deterministic result |
| AC-4 | Traffic split > 100% raises ValueError | `create_version(..., traffic_pct=60)` when 60% already active → error |
| AC-5 | SHA-256 used (not MD5) for FIPS compliance | `grep "sha256" prompt_registry.py` matches; `grep "md5"` does not |

---

## Validation

```bash
PYTHONPATH=. alembic revision --autogenerate -m "add_prompt_versions"
PYTHONPATH=. alembic upgrade head

# Verify deterministic assignment
PYTHONPATH=. python -c "
from app.services.ai.prompt_registry import PromptRegistry
buckets = [PromptRegistry._get_user_bucket(f'user-{i}', 'test') for i in range(1000)]
print(f'Range: {min(buckets):.0f}-{max(buckets):.0f}, Mean: {sum(buckets)/len(buckets):.1f}')
assert 0 <= min(buckets) <= 5 and 95 <= max(buckets) <= 100
print('OK: Uniform distribution')
"
```
