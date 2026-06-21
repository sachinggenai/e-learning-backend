"""RLHF Feedback Collector — US-PEND-025.

Tracks which AI proposals users accept, modify, or reject.
Computes acceptance rates for data-driven prompt improvement.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feedback import AIFeedbackRecord

logger = logging.getLogger(__name__)


class FeedbackCollector:
    """Collects human feedback on AI-generated content for RLHF."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self, proposal_id, user_id, action,
        generated_content=None, applied_content=None,
        session_id=None, course_id=None, prompt_version=None,
        model_id=None, template_type=None, rejection_reason=None,
        time_to_decision_ms=None,
    ) -> AIFeedbackRecord:
        edit_distance = None
        edit_ratio = None
        if generated_content and applied_content:
            dist, ratio = self._compute_edit_distance(
                str(generated_content), str(applied_content)
            )
            edit_distance = dist
            edit_ratio = ratio

        record = AIFeedbackRecord(
            proposal_id=proposal_id, session_id=session_id,
            user_id=user_id, course_id=course_id, action=action,
            generated_content=generated_content,
            applied_content=applied_content,
            edit_distance=edit_distance, edit_ratio=edit_ratio,
            prompt_version=prompt_version, model_id=model_id,
            template_type=template_type,
            rejection_reason=rejection_reason,
            time_to_decision_ms=time_to_decision_ms,
        )
        self.db.add(record)
        await self.db.commit()
        return record

    async def get_acceptance_rate(self, user_id=None, course_id=None,
                                   since_days=30) -> Dict[str, Any]:
        stmt = (
            select(AIFeedbackRecord.action, func.count(AIFeedbackRecord.id))
            .where(AIFeedbackRecord.created_at >= func.now() - func.make_interval(since_days))
        )
        if user_id:
            stmt = stmt.where(AIFeedbackRecord.user_id == user_id)
        if course_id:
            stmt = stmt.where(AIFeedbackRecord.course_id == course_id)

        result = await self.db.execute(stmt)
        rows = result.all()
        counts = {r.action: r.count for r in rows}
        total = sum(counts.values())
        return {
            "total_decisions": total,
            "accepted": counts.get("accepted", 0),
            "modified": counts.get("modified", 0),
            "rejected": counts.get("rejected", 0),
            "acceptance_rate": counts.get("accepted", 0) / total if total else 0.0,
            "modification_rate": counts.get("modified", 0) / total if total else 0.0,
            "rejection_rate": counts.get("rejected", 0) / total if total else 0.0,
            "period_days": since_days,
        }

    @staticmethod
    def _compute_edit_distance(a: str, b: str) -> tuple:
        if not a and not b:
            return 0, 0.0
        m, n = len(a), len(b)
        if m == 0 or n == 0:
            return max(m, n), 1.0
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
        return dp[m][n], dp[m][n] / max_len
