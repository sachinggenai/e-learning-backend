# US-BKND-AI-043: Concurrency Control and Page Locking

**Status:** ✅ COMPLETE
**Priority:** MUST
**Sprint:** 7
**Implemented:** 2026-06-15

## Summary

In-process lock manager for AI authoring concurrency control. Supports READ (shared), WRITE (exclusive), and SESSION (course-level) locks with automatic TTL expiry, heartbeat refresh, conflict detection with lock holder info, session-level bulk release, stale lock cleanup, and monitoring stats.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/lock_manager.py` | NEW | LockManager with READ/WRITE/SESSION locks, heartbeat, expiry, conflict detection, stats |
| `tests/run_concurrency_tests.py` | NEW | 43 tests covering acquisition, conflicts, heartbeat, expiry, release, cleanup |

## Lock Types

| Type | Sharing | Default TTL | Use Case |
|---|---|---|---|
| READ | Multiple concurrent | 60s | fetch_page, list_pages |
| WRITE | Exclusive per resource | 900s (15min) | propose_create/update/delete |
| SESSION | Exclusive per course | 3600s (1hr) | One AI session per course at a time |

## Key Design Decisions

1. **In-process MVP** — Single-instance in-memory locks; replaceable with Redis for multi-instance
2. **Re-entrant writes** — Same session can acquire multiple WRITE locks on the same resource
3. **Stale lock auto-cleanup** — `cleanup_expired()` releases expired locks; called on every query
4. **Heartbeat refresh** — `heartbeat(lock_id)` extends TTL by the original duration
5. **Global singleton** — `get_lock_manager()` returns the shared LockManager instance
6. **Structured conflicts** — LockError includes lock holder identity, remaining time, and resource details

## See Also

- [US-AI-043 Full Spec](../US-AI-043_CONCURRENCY_CONTROL_PAGE_LOCKING.md) — Complete specification
