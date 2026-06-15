"""Admin Audit Query Service - US-BKND-AI-020.

Provides filtered querying, aggregation, and export of AI audit logs.
Read-only operations for compliance dashboards and admin review.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AuditQueryService:
    """Query service for AI audit logs with filtering and aggregation.

    In production, queries the ai_audit_logs table. For MVP, provides
    an in-memory store for testing.
    """

    def __init__(self):
        self._audit_log: List[Dict[str, Any]] = []

    def record(self, entry: Dict[str, Any]) -> None:
        """Record an audit entry (for testing)."""
        entry["recorded_at"] = datetime.utcnow().isoformat()
        self._audit_log.append(entry)

    def query(
        self,
        user_id: Optional[str] = None,
        course_id: Optional[str] = None,
        operation: Optional[str] = None,
        session_id: Optional[str] = None,
        outcome: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """Query audit logs with filters and pagination."""
        results = list(self._audit_log)

        # Apply filters
        if user_id:
            results = [r for r in results if r.get("user_id") == user_id]
        if course_id:
            results = [r for r in results if r.get("course_id") == course_id]
        if operation:
            results = [r for r in results if r.get("operation") == operation]
        if session_id:
            results = [r for r in results if r.get("session_id") == session_id]
        if outcome:
            results = [r for r in results if r.get("outcome") == outcome]
        if date_from:
            results = [r for r in results if r.get("recorded_at", "") >= date_from]
        if date_to:
            results = [r for r in results if r.get("recorded_at", "") <= date_to]
        if search:
            term = search.lower()
            results = [r for r in results if term in str(r).lower()]

        # Sort by time desc
        results.sort(key=lambda r: r.get("recorded_at", ""), reverse=True)

        total = len(results)
        start = (page - 1) * page_size
        page_items = results[start:start + page_size]

        return {
            "items": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    def get_operations_summary(self, days: int = 7) -> Dict[str, Any]:
        """Aggregate operations summary for compliance dashboard."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        recent = [r for r in self._audit_log if r.get("recorded_at", "") >= cutoff]

        by_operation: Dict[str, int] = {}
        by_outcome: Dict[str, int] = {}
        by_user: Dict[str, int] = {}
        by_course: Dict[str, int] = {}

        for r in recent:
            op = r.get("operation", "unknown")
            out = r.get("outcome", "unknown")
            uid = r.get("user_id", "unknown")
            cid = r.get("course_id", "unknown")
            by_operation[op] = by_operation.get(op, 0) + 1
            by_outcome[out] = by_outcome.get(out, 0) + 1
            by_user[uid] = by_user.get(uid, 0) + 1
            by_course[cid] = by_course.get(cid, 0) + 1

        return {
            "period_days": days,
            "total_operations": len(recent),
            "by_operation": by_operation,
            "by_outcome": by_outcome,
            "by_user": {k: v for k, v in sorted(by_user.items(), key=lambda x: -x[1])[:10]},
            "by_course": {k: v for k, v in sorted(by_course.items(), key=lambda x: -x[1])[:10]},
        }

    def get_course_history(self, course_id: str) -> Dict[str, Any]:
        """Get time-ordered change history for a course."""
        entries = [r for r in self._audit_log if r.get("course_id") == course_id]
        entries.sort(key=lambda r: r.get("recorded_at", ""), reverse=True)

        return {
            "course_id": course_id,
            "total_mutations": len(entries),
            "history": [
                {
                    "operation": e.get("operation"),
                    "outcome": e.get("outcome"),
                    "user_id": e.get("user_id"),
                    "timestamp": e.get("recorded_at"),
                    "summary": e.get("summary", ""),
                    "proposal_id": e.get("proposal_id"),
                }
                for e in entries[:100]
            ],
        }
