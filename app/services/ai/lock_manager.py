"""Page Lock Manager - US-BKND-AI-043.

In-process lock manager for AI authoring concurrency control. Supports:
- READ locks (shared, multiple readers)
- WRITE locks (exclusive, one writer per page)
- SESSION locks (course-level, prevents concurrent AI sessions)
- Automatic TTL expiry with heartbeat refresh
- Conflict detection with lock holder info
- Stale lock cleanup

For MVP, locks are in-memory. Production should use Redis for
multi-instance deployment.
"""

from __future__ import annotations

import time
import uuid
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


class LockType(str, Enum):
    READ = "read"
    WRITE = "write"
    SESSION = "session"


# Default TTLs in seconds
DEFAULT_READ_TTL = 60        # 1 minute
DEFAULT_WRITE_TTL = 900      # 15 minutes
DEFAULT_SESSION_TTL = 3600   # 1 hour
DEFAULT_HEARTBEAT_INTERVAL = 300  # 5 minutes

# Cleanup interval in seconds
CLEANUP_INTERVAL = 60


class LockError(Exception):
    """Structured error for lock conflicts."""
    def __init__(self, code: str, message: str, details: Optional[Dict] = None,
                 http_status: int = 409):
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status
        super().__init__(message)


class PageLock:
    """A lock on a page or course resource."""

    def __init__(
        self,
        lock_id: str,
        resource_id: str,
        lock_type: LockType,
        session_id: str,
        user_id: str,
        user_name: str = "",
        ttl_seconds: int = DEFAULT_WRITE_TTL,
    ):
        self.lock_id = lock_id
        self.resource_id = resource_id
        self.lock_type = lock_type
        self.session_id = session_id
        self.user_id = user_id
        self.user_name = user_name
        self.ttl_seconds = ttl_seconds
        self.acquired_at = time.time()
        self.expires_at = self.acquired_at + ttl_seconds
        self.last_heartbeat = self.acquired_at

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    def heartbeat(self) -> None:
        """Extend lock TTL by the heartbeat interval."""
        self.last_heartbeat = time.time()
        self.expires_at = time.time() + self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lock_id": self.lock_id,
            "resource_id": self.resource_id,
            "lock_type": self.lock_type.value,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "acquired_at": datetime.fromtimestamp(
                self.acquired_at, tz=timezone.utc
            ).isoformat(),
            "expires_at": datetime.fromtimestamp(
                self.expires_at, tz=timezone.utc
            ).isoformat(),
            "remaining_seconds": self.remaining_seconds,
        }


class LockManager:
    """In-process lock manager for AI authoring concurrency.

    Usage:
        mgr = LockManager()
        lock = mgr.acquire_write_lock("page_42", "sess_1", "user_1")
        # ...
        mgr.release_lock(lock.lock_id)
    """

    def __init__(self):
        self._locks: Dict[str, PageLock] = {}       # lock_id -> PageLock
        self._resource_locks: Dict[str, List[str]] = {}  # resource_id -> [lock_id]
        self._session_locks: Dict[str, List[str]] = {}   # session_id -> [lock_id]
        self._conflict_queues: Dict[str, List[str]] = {} # resource_id -> [session_id]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire_write_lock(
        self,
        resource_id: str,
        session_id: str,
        user_id: str,
        user_name: str = "",
        ttl_seconds: int = DEFAULT_WRITE_TTL,
    ) -> PageLock:
        """Acquire an exclusive WRITE lock on a resource.

        Fails if another session holds a WRITE lock.
        READ locks from other sessions don't block writes.
        """
        # Check for existing WRITE lock from another session
        existing = self._get_locks_for_resource(resource_id)
        for lock in existing:
            if lock.lock_type == LockType.WRITE and lock.session_id != session_id:
                if not lock.is_expired:
                    raise LockError(
                        "PAGE_LOCKED",
                        f"Resource '{resource_id}' is locked by {lock.user_name or lock.user_id} "
                        f"(session {lock.session_id}). Auto-release in ~{lock.remaining_seconds}s.",
                        details={
                            "resource_id": resource_id,
                            "lock_holder_user_id": lock.user_id,
                            "lock_holder_name": lock.user_name,
                            "lock_acquired_at": datetime.fromtimestamp(
                                lock.acquired_at, tz=timezone.utc
                            ).isoformat(),
                            "ttl_seconds_remaining": lock.remaining_seconds,
                        },
                        http_status=409,
                    )

        # Check for SESSION lock on course (different session)
        for lock in existing:
            if lock.lock_type == LockType.SESSION and lock.session_id != session_id:
                if not lock.is_expired:
                    raise LockError(
                        "COURSE_LOCKED",
                        f"Course is locked by another AI session (session {lock.session_id}).",
                        details={"lock_holder_session_id": lock.session_id},
                        http_status=409,
                    )

        return self._create_lock(
            resource_id, LockType.WRITE, session_id, user_id, user_name, ttl_seconds
        )

    def acquire_read_lock(
        self,
        resource_id: str,
        session_id: str,
        user_id: str,
        ttl_seconds: int = DEFAULT_READ_TTL,
    ) -> PageLock:
        """Acquire a shared READ lock on a resource.

        Multiple readers can hold READ locks simultaneously.
        READ locks don't block other READ locks.
        """
        return self._create_lock(
            resource_id, LockType.READ, session_id, user_id, "", ttl_seconds
        )

    def acquire_session_lock(
        self,
        course_id: str,
        session_id: str,
        user_id: str,
        user_name: str = "",
        ttl_seconds: int = DEFAULT_SESSION_TTL,
    ) -> PageLock:
        """Acquire a SESSION lock on a course (only one AI session per course)."""
        existing = self._get_locks_for_resource(course_id)
        for lock in existing:
            if lock.lock_type == LockType.SESSION and lock.session_id != session_id:
                if not lock.is_expired:
                    raise LockError(
                        "COURSE_LOCKED",
                        f"Another AI session is already active on this course "
                        f"({lock.user_name or lock.user_id}).",
                        details={
                            "lock_holder_user_id": lock.user_id,
                            "lock_holder_name": lock.user_name,
                        },
                        http_status=409,
                    )

        return self._create_lock(
            course_id, LockType.SESSION, session_id, user_id, user_name, ttl_seconds
        )

    def release_lock(self, lock_id: str) -> bool:
        """Release a lock by ID. Returns True if lock was found and released."""
        lock = self._locks.pop(lock_id, None)
        if lock is None:
            return False

        # Remove from resource index
        rid_locks = self._resource_locks.get(lock.resource_id, [])
        if lock_id in rid_locks:
            rid_locks.remove(lock_id)

        # Remove from session index
        sid_locks = self._session_locks.get(lock.session_id, [])
        if lock_id in sid_locks:
            sid_locks.remove(lock_id)

        logger.info(
            "Lock released: id=%s resource=%s type=%s session=%s",
            lock_id, lock.resource_id, lock.lock_type.value, lock.session_id,
        )
        return True

    def release_session_locks(self, session_id: str) -> int:
        """Release all locks held by a session. Returns count released."""
        lock_ids = list(self._session_locks.get(session_id, []))
        count = 0
        for lid in lock_ids:
            if self.release_lock(lid):
                count += 1
        return count

    def heartbeat(self, lock_id: str) -> Optional[PageLock]:
        """Refresh a lock's TTL. Returns the lock or None if not found."""
        lock = self._locks.get(lock_id)
        if lock is None:
            return None
        if lock.is_expired:
            self.release_lock(lock_id)
            return None
        lock.heartbeat()
        return lock

    def get_lock(self, lock_id: str) -> Optional[PageLock]:
        """Get a lock by ID."""
        return self._locks.get(lock_id)

    def get_locks_for_resource(self, resource_id: str) -> List[PageLock]:
        """Get all active locks for a resource."""
        self._cleanup_expired()
        return [
            l for l in self._get_locks_for_resource(resource_id)
            if not l.is_expired
        ]

    def get_locks_for_session(self, session_id: str) -> List[PageLock]:
        """Get all active locks held by a session."""
        self._cleanup_expired()
        return [
            l for l in self._get_locks_for_session(session_id)
            if not l.is_expired
        ]

    def get_all_active_locks(self) -> List[PageLock]:
        """Get all active (non-expired) locks."""
        self._cleanup_expired()
        return [l for l in self._locks.values() if not l.is_expired]

    def is_resource_locked(self, resource_id: str, session_id: str = "") -> bool:
        """Check if a resource has an active WRITE lock.

        If session_id is provided, locks from the same session don't count.
        """
        for lock in self._get_locks_for_resource(resource_id):
            if lock.is_expired:
                continue
            if lock.lock_type in (LockType.WRITE, LockType.SESSION):
                if session_id and lock.session_id == session_id:
                    continue  # Same session — not blocked
                return True
        return False

    def cleanup_expired(self) -> int:
        """Release all expired locks. Returns count cleaned up."""
        return self._cleanup_expired()

    def get_stats(self) -> Dict[str, Any]:
        """Return lock statistics for monitoring."""
        active = self.get_all_active_locks()
        return {
            "total_locks": len(self._locks),
            "active_locks": len(active),
            "expired_locks": len(self._locks) - len(active),
            "by_type": {
                "read": len([l for l in active if l.lock_type == LockType.READ]),
                "write": len([l for l in active if l.lock_type == LockType.WRITE]),
                "session": len([l for l in active if l.lock_type == LockType.SESSION]),
            },
            "conflict_queues": sum(
                len(q) for q in self._conflict_queues.values()
            ),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _create_lock(
        self, resource_id: str, lock_type: LockType,
        session_id: str, user_id: str, user_name: str, ttl_seconds: int,
    ) -> PageLock:
        """Create and register a new lock."""
        lock_id = str(uuid.uuid4())[:12]
        lock = PageLock(
            lock_id=lock_id,
            resource_id=resource_id,
            lock_type=lock_type,
            session_id=session_id,
            user_id=user_id,
            user_name=user_name,
            ttl_seconds=ttl_seconds,
        )

        self._locks[lock_id] = lock
        self._resource_locks.setdefault(resource_id, []).append(lock_id)
        self._session_locks.setdefault(session_id, []).append(lock_id)

        logger.debug(
            "Lock acquired: id=%s resource=%s type=%s session=%s ttl=%ds",
            lock_id, resource_id, lock_type.value, session_id, ttl_seconds,
        )
        return lock

    def _get_locks_for_resource(self, resource_id: str) -> List[PageLock]:
        return [
            self._locks[lid]
            for lid in self._resource_locks.get(resource_id, [])
            if lid in self._locks
        ]

    def _get_locks_for_session(self, session_id: str) -> List[PageLock]:
        return [
            self._locks[lid]
            for lid in self._session_locks.get(session_id, [])
            if lid in self._locks
        ]

    def _cleanup_expired(self) -> int:
        """Remove all expired locks. Returns count removed."""
        expired_ids = [
            lid for lid, lock in self._locks.items()
            if lock.is_expired
        ]
        for lid in expired_ids:
            self.release_lock(lid)
        if expired_ids:
            logger.info("Cleaned up %d expired locks", len(expired_ids))
        return len(expired_ids)


# Global singleton for the app
_lock_manager: Optional[LockManager] = None


def get_lock_manager() -> LockManager:
    """Get or create the global LockManager singleton."""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager
