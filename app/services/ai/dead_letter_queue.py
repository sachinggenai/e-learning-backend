"""Dead Letter Queue and Failed Job Recovery - US-BKND-AI-048.

Captures failed AI jobs (proposals, ingestion, generation), classifies
failure types, implements retry with exponential backoff, and provides
admin endpoints for manual recovery.

Architecture:
    Failed job -> DeadLetterQueue.enqueue() -> classify failure
    Retry policy: exponential backoff with max attempts
    Admin can: list, retry, or discard failed jobs
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FailureCategory(str, Enum):
    TRANSIENT = "transient"      # Timeout, rate limit, network — retryable
    PERMANENT = "permanent"      # Validation, auth, not found — not retryable
    PROVIDER = "provider"        # LLM provider error — retryable after cooldown
    UNKNOWN = "unknown"          # Unclassified — retryable with caution


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD = "dead"            # Max retries exhausted
    RECOVERED = "recovered"  # Manually recovered
    DISCARDED = "discarded"  # Admin discarded


# Failure classification patterns
FAILURE_PATTERNS: Dict[str, FailureCategory] = {
    # Provider-specific patterns (must come before generic ones)
    "anthropic": FailureCategory.PROVIDER,
    "openai": FailureCategory.PROVIDER,
    "llm provider": FailureCategory.PROVIDER,
    # Transient patterns
    "timeout": FailureCategory.TRANSIENT,
    "rate limit": FailureCategory.TRANSIENT,
    "overloaded": FailureCategory.TRANSIENT,
    "connection": FailureCategory.TRANSIENT,
    "network": FailureCategory.TRANSIENT,
    "503": FailureCategory.TRANSIENT,
    "500": FailureCategory.TRANSIENT,
    "429": FailureCategory.TRANSIENT,
    # Permanent patterns
    "validation": FailureCategory.PERMANENT,
    "invalid": FailureCategory.PERMANENT,
    "not found": FailureCategory.PERMANENT,
    "unauthorized": FailureCategory.PERMANENT,
    "forbidden": FailureCategory.PERMANENT,
    "quota": FailureCategory.PERMANENT,
}


class DeadLetterJob:
    """A failed job in the dead letter queue."""

    def __init__(
        self,
        job_id: str,
        job_type: str,
        session_id: str,
        user_id: str,
        error_message: str,
        original_payload: Dict[str, Any],
        max_retries: int = 3,
    ):
        self.job_id = job_id
        self.job_type = job_type  # "proposal", "ingestion", "generation", "chat_turn"
        self.session_id = session_id
        self.user_id = user_id
        self.error_message = error_message
        self.original_payload = original_payload
        self.max_retries = max_retries
        self.retry_count = 0
        self.status = JobStatus.FAILED
        self.failure_category = self._classify(error_message)
        self.created_at = datetime.now(timezone.utc)
        self.last_retry_at: Optional[datetime] = None
        self.next_retry_at: Optional[datetime] = None

    @staticmethod
    def _classify(error: str) -> FailureCategory:
        """Classify failure from error message patterns."""
        lower = error.lower()
        for pattern, category in FAILURE_PATTERNS.items():
            if pattern in lower:
                return category
        return FailureCategory.UNKNOWN

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries and self.status != JobStatus.DISCARDED

    def retry_backoff_seconds(self) -> int:
        """Exponential backoff: 2^retry_count * 5 seconds, max 5 minutes."""
        return min(2 ** self.retry_count * 5, 300)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "error_message": self.error_message[:200],
            "failure_category": self.failure_category.value,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat(),
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "backoff_seconds": self.retry_backoff_seconds(),
        }


class DeadLetterQueue:
    """Manages failed AI jobs with retry and recovery capabilities.

    Usage:
        dlq = DeadLetterQueue()
        dlq.enqueue(job_id, job_type, session_id, user_id, error, payload)
        stats = dlq.get_stats()
    """

    MAX_JOBS = 1000  # In-memory limit for MVP

    def __init__(self):
        self._jobs: Dict[str, DeadLetterJob] = {}

    def enqueue(
        self,
        job_id: str,
        job_type: str,
        session_id: str,
        user_id: str,
        error_message: str,
        original_payload: Dict[str, Any],
        max_retries: int = 3,
    ) -> DeadLetterJob:
        """Add a failed job to the dead letter queue."""
        if len(self._jobs) >= self.MAX_JOBS:
            # Evict oldest dead job
            dead_jobs = [
                jid for jid, j in self._jobs.items()
                if j.status == JobStatus.DEAD
            ]
            if dead_jobs:
                del self._jobs[dead_jobs[0]]

        job = DeadLetterJob(
            job_id=job_id, job_type=job_type,
            session_id=session_id, user_id=user_id,
            error_message=error_message,
            original_payload=original_payload,
            max_retries=max_retries,
        )
        self._jobs[job_id] = job

        logger.warning(
            "DLQ enqueue: job=%s type=%s category=%s error=%s",
            job_id, job_type, job.failure_category.value, error_message[:100],
        )
        return job

    def retry_job(self, job_id: str) -> Optional[DeadLetterJob]:
        """Attempt to retry a failed job. Returns job if retry scheduled."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if not job.can_retry():
            job.status = JobStatus.DEAD
            logger.info("DLQ job dead: %s (retries exhausted)", job_id)
            return job

        job.retry_count += 1
        job.status = JobStatus.RETRYING
        job.last_retry_at = datetime.now(timezone.utc)
        job.next_retry_at = datetime.fromtimestamp(
            time.time() + job.retry_backoff_seconds(),
            tz=timezone.utc,
        )

        logger.info(
            "DLQ retry: job=%s attempt=%d/%d backoff=%ds",
            job_id, job.retry_count, job.max_retries, job.retry_backoff_seconds(),
        )
        return job

    def mark_recovered(self, job_id: str) -> bool:
        """Mark a job as successfully recovered."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.status = JobStatus.RECOVERED
        return True

    def mark_discarded(self, job_id: str) -> bool:
        """Admin-discard a dead letter job."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.status = JobStatus.DISCARDED
        return True

    def get_job(self, job_id: str) -> Optional[DeadLetterJob]:
        return self._jobs.get(job_id)

    def list_jobs(
        self,
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[DeadLetterJob]:
        """List DLQ jobs with optional filters."""
        results = list(self._jobs.values())
        if status:
            results = [j for j in results if j.status.value == status]
        if job_type:
            results = [j for j in results if j.job_type == job_type]
        if category:
            results = [j for j in results if j.failure_category.value == category]
        return sorted(results, key=lambda j: j.created_at, reverse=True)

    def get_stats(self) -> Dict[str, Any]:
        """Get DLQ statistics for monitoring."""
        jobs = list(self._jobs.values())
        by_status: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        by_type: Dict[str, int] = {}

        for j in jobs:
            by_status[j.status.value] = by_status.get(j.status.value, 0) + 1
            by_category[j.failure_category.value] = by_category.get(j.failure_category.value, 0) + 1
            by_type[j.job_type] = by_type.get(j.job_type, 0) + 1

        return {
            "total_jobs": len(jobs),
            "by_status": by_status,
            "by_category": by_category,
            "by_type": by_type,
            "pending_retry": len([
                j for j in jobs
                if j.status in (JobStatus.FAILED, JobStatus.RETRYING)
                and j.can_retry()
            ]),
        }

    def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """Remove recovered/discarded jobs older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        removed = 0
        for jid in list(self._jobs.keys()):
            job = self._jobs[jid]
            if job.status in (JobStatus.RECOVERED, JobStatus.DISCARDED):
                if job.created_at.timestamp() < cutoff:
                    del self._jobs[jid]
                    removed += 1
        return removed


# Global singleton
_dlq: Optional[DeadLetterQueue] = None


def get_dlq() -> DeadLetterQueue:
    global _dlq
    if _dlq is None:
        _dlq = DeadLetterQueue()
    return _dlq
