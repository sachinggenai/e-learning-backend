# US-PEND-025: RLHF Feedback Collection Baseline — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟡 HIGH |
| **Batch** | 7 — Long-Term / Blocked |
| **Depends On** | US-PEND-024 (Kafka/Redpanda for events) |
| **Estimated Effort** | 5-7 days |
| **Target Files** | New: `app/services/ai/feedback_collector.py`, `app/models/ai_feedback.py`, `app/repositories/ai_feedback_repo.py`, `alembic/versions/*_add_ai_feedback.py`. Modify: `app/services/ai/proposal_service.py`, `app/services/ai/chat_orchestrator.py` |

---

## User Story

**As a** product manager improving AI quality,
**I want** to track which AI proposals users accept, modify, or reject,
**So that** I can measure AI effectiveness over time and drive data-informed prompt improvements.

---

## Current State (Code Verified 2026-06-21)

- ❌ No feedback collection mechanism exists
- ❌ `test -f app/services/ai/feedback_collector.py` → NOT FOUND
- ❌ `test -f app/models/ai_feedback.py` → NOT FOUND
- ❌ No tracking of: proposal acceptance rate, user modification rate, rejection reasons
- ✅ `proposal_service.py` exists with `apply_proposal()`, `cancel_proposal()` — integration points
- ✅ `chat_orchestrator.py` exists — integration point for implicit feedback
- ✅ `AIProposalRecord` model has `status` field that transitions: `pending → applied/rejected/expired`

---

## 🔧 Open-Source Tooling

**No new libraries needed for MVP.** Uses only:
- Existing `SQLAlchemy` ORM (already in project)
- Existing `Alembic` for migrations (already in project)
- Existing `KafkaEventPublisher` (from US-PEND-024) for async event publishing

---

## Enriched Implementation

### File: `app/models/ai_feedback.py`

```python
"""AI Feedback model for RLHF data collection — US-PEND-025."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, String, Float, DateTime, ForeignKey, Text, Integer, JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.config import Base

class AIFeedbackRecord(Base):
    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    feedback_id: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: str(uuid.uuid4())
    )
    proposal_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("ai_proposals.proposal_id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    course_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Feedback action: accepted, modified, rejected, ignored, undo
    action: Mapped[str] = mapped_column(String(32), nullable=False)

    # Content comparison
    generated_content: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    applied_content: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    edit_distance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    edit_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Context
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    template_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Metadata
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    time_to_decision_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
```

### File: `app/services/ai/feedback_collector.py`

```python
"""RLHF Feedback Collector — US-PEND-025."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feedback import AIFeedbackRecord

logger = logging.getLogger(__name__)


class FeedbackCollector:
    """Collects human feedback on AI-generated content for RLHF.

    Usage:
        collector = FeedbackCollector(db_session)
        await collector.record(
            proposal_id="...",
            user_id="...",
            action="accepted",
            generated_content={...},
            applied_content={...},
        )
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        proposal_id: str,
        user_id: str,
        action: str,  # accepted, modified, rejected, ignored, undo
        generated_content: Dict[str, Any],
        applied_content: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        course_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_id: Optional[str] = None,
        template_type: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        time_to_decision_ms: Optional[int] = None,
    ) -> AIFeedbackRecord:
        """Record a feedback event."""
        # Compute edit distance if both contents provided
        edit_distance = None
        edit_ratio = None
        if generated_content and applied_content:
            dist, ratio = self._compute_edit_distance(
                str(generated_content), str(applied_content)
            )
            edit_distance = dist
            edit_ratio = ratio

        record = AIFeedbackRecord(
            proposal_id=proposal_id,
            session_id=session_id,
            user_id=user_id,
            course_id=course_id,
            action=action,
            generated_content=generated_content,
            applied_content=applied_content,
            edit_distance=edit_distance,
            edit_ratio=edit_ratio,
            prompt_version=prompt_version,
            model_id=model_id,
            template_type=template_type,
            rejection_reason=rejection_reason,
            time_to_decision_ms=time_to_decision_ms,
        )
        self.db.add(record)
        await self.db.commit()
        logger.debug("Feedback recorded: %s -> %s", proposal_id, action)
        return record

    async def get_acceptance_rate(
        self,
        user_id: Optional[str] = None,
        course_id: Optional[str] = None,
        since_days: int = 30,
    ) -> Dict[str, Any]:
        """Compute acceptance rate metrics."""
        from sqlalchemy import func, select

        stmt = select(
            AIFeedbackRecord.action,
            func.count(AIFeedbackRecord.id).label("count"),
        ).where(
            AIFeedbackRecord.created_at >= func.now() - func.make_interval(since_days)
        )
        if user_id:
            stmt = stmt.where(AIFeedbackRecord.user_id == user_id)
        if course_id:
            stmt = stmt.where(AIFeedbackRecord.course_id == course_id)

        result = await self.db.execute(stmt)
        rows = result.all()

        counts = {row.action: row.count for row in rows}
        total = sum(counts.values())
        accepted = counts.get("accepted", 0)
        modified = counts.get("modified", 0)
        rejected = counts.get("rejected", 0)

        return {
            "total_decisions": total,
            "accepted": accepted,
            "modified": modified,
            "rejected": rejected,
            "acceptance_rate": accepted / total if total > 0 else 0.0,
            "modification_rate": modified / total if total > 0 else 0.0,
            "rejection_rate": rejected / total if total > 0 else 0.0,
            "period_days": since_days,
        }

    @staticmethod
    def _compute_edit_distance(a: str, b: str) -> tuple:
        """Levenshtein distance between two strings."""
        if not a and not b:
            return 0, 0.0
        # Simple Levenshtein (no external lib needed for MVP)
        m, n = len(a), len(b)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if a[i-1] == b[j-1] else 1
                dp[i][j] = min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + cost)
        max_len = max(m, n)
        return dp[m][n], dp[m][n] / max_len if max_len > 0 else 0.0
```

### Integration in `proposal_service.py`

```python
# In AIProposalService.apply_proposal() — after successful apply:
from app.services.ai.feedback_collector import FeedbackCollector

feedback = FeedbackCollector(self.db)
await feedback.record(
    proposal_id=proposal_id,
    user_id=user_id,
    action="accepted",
    generated_content=proposal.data,
    applied_content=after_state,
    session_id=session_id,
    course_id=course_id,
    template_type=proposal.resource_type,
    time_to_decision_ms=(datetime.utcnow() - proposal.created_at).total_seconds() * 1000,
)
```

### Database Migration

```bash
# Create migration
PYTHONPATH=. alembic revision --autogenerate -m "add_ai_feedback_table"
PYTHONPATH=. alembic upgrade head
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Every applied/rejected proposal generates a feedback record | Query `ai_feedback` table after proposal lifecycle |
| AC-2 | Feedback queryable by date range, course_id, user_id | `SELECT * FROM ai_feedback WHERE user_id = '...' AND created_at > '...'` |
| AC-3 | Acceptance rate metric available | `GET /api/v1/admin/ai/feedback/summary` returns `acceptance_rate` |
| AC-4 | Zero performance impact on proposal apply | Feedback recorded synchronously but within existing DB transaction |

---

## Validation

```bash
# Create migration
PYTHONPATH=. alembic revision --autogenerate -m "add_ai_feedback_table"
PYTHONPATH=. alembic upgrade head

# Verify table
psql -c "\d ai_feedback"

# Run tests
python tests/run_final_stories_tests.py
```
