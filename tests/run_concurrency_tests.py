"""Standalone test runner for US-BKND-AI-043 - Concurrency Control.

Tests LockManager: WRITE/READ/SESSION lock acquisition, conflict detection,
heartbeat, expiry, release, cleanup, stats.
"""
import time
from unittest.mock import patch

from app.services.ai.lock_manager import (
    LockManager, PageLock, LockType, LockError,
    DEFAULT_READ_TTL, DEFAULT_WRITE_TTL, DEFAULT_SESSION_TTL,
)

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        failures.append((name, detail))
        print(f"  FAIL: {name} -- {detail}")


def main():
    global passed, failed

    # ===============================================================
    # Lock Acquisition
    # ===============================================================
    print("=== Lock Acquisition ===")
    mgr = LockManager()

    # 1. Acquire write lock
    lock = mgr.acquire_write_lock("page_42", "sess_a", "user_alice", "Alice")
    check("acquires write lock", lock is not None)
    check("has lock_id", len(lock.lock_id) > 0)
    check("write lock type", lock.lock_type == LockType.WRITE)
    check("resource is page_42", lock.resource_id == "page_42")
    check("session is sess_a", lock.session_id == "sess_a")
    check("user is user_alice", lock.user_id == "user_alice")
    check("user_name is Alice", lock.user_name == "Alice")

    # 2. Acquire read lock (shared)
    lock2 = mgr.acquire_read_lock("page_42", "sess_b", "user_bob")
    check("acquires read lock", lock2.lock_type == LockType.READ)

    # 3. Read lock doesn't block read lock
    lock3 = mgr.acquire_read_lock("page_42", "sess_c", "user_carol")
    check("multiple read locks allowed", lock3 is not None)

    # ===============================================================
    # Write Lock Conflicts
    # ===============================================================
    print("\n=== Write Lock Conflicts ===")
    mgr2 = LockManager()
    mgr2.acquire_write_lock("page_1", "sess_a", "user_a", "Alice")

    # 4. Different session can't write-lock same page
    try:
        mgr2.acquire_write_lock("page_1", "sess_b", "user_b", "Bob")
        check("write lock conflict detected", False, "should raise LockError")
    except LockError as e:
        check("write lock conflict detected", e.code == "PAGE_LOCKED")
        check("conflict has details", "lock_holder_user_id" in e.details)
        check("conflict has remaining time", "ttl_seconds_remaining" in e.details)

    # 5. Same session CAN write-lock same page (re-entrant)
    try:
        lock_re = mgr2.acquire_write_lock("page_1", "sess_a", "user_a", "Alice")
        check("same session re-entrant write OK", lock_re is not None)
    except LockError:
        check("same session re-entrant write OK", False, "should allow re-entrant")

    # 6. Different page unaffected
    lock_diff = mgr2.acquire_write_lock("page_2", "sess_b", "user_b")
    check("different page not blocked", lock_diff is not None)

    # ===============================================================
    # Session Locks
    # ===============================================================
    print("\n=== Session Locks ===")
    mgr3 = LockManager()
    mgr3.acquire_session_lock("course_1", "sess_a", "user_a", "Alice")

    # 7. Different session can't session-lock same course
    try:
        mgr3.acquire_session_lock("course_1", "sess_b", "user_b", "Bob")
        check("session lock conflict detected", False, "should raise")
    except LockError as e:
        check("session lock conflict detected", e.code == "COURSE_LOCKED")

    # 8. Different course unaffected
    lock_sess = mgr3.acquire_session_lock("course_2", "sess_b", "user_b")
    check("different course session lock OK", lock_sess is not None)

    # ===============================================================
    # Heartbeat
    # ===============================================================
    print("\n=== Heartbeat ===")
    mgr4 = LockManager()
    lock4 = mgr4.acquire_write_lock("page_hb", "sess_x", "user_x", ttl_seconds=10)
    original_expiry = lock4.expires_at

    # 9. Heartbeat extends TTL
    time.sleep(0.01)  # Small delay
    result = mgr4.heartbeat(lock4.lock_id)
    check("heartbeat succeeds", result is not None)
    check("heartbeat extends expiry", result.expires_at > original_expiry)

    # 10. Heartbeat on nonexistent lock
    result = mgr4.heartbeat("nonexistent")
    check("heartbeat nonexistent returns None", result is None)

    # ===============================================================
    # Lock Release
    # ===============================================================
    print("\n=== Lock Release ===")
    mgr5 = LockManager()
    lock5 = mgr5.acquire_write_lock("page_rel", "sess_r", "user_r")
    check("lock acquired", lock5 is not None)

    # 11. Release by lock_id
    released = mgr5.release_lock(lock5.lock_id)
    check("release succeeds", released)

    # 12. Released lock not blocking
    try:
        mgr5.acquire_write_lock("page_rel", "sess_new", "user_new")
        check("released page now available", True)
    except LockError:
        check("released page now available", False, "should be available")

    # 13. Release nonexistent lock
    released = mgr5.release_lock("nonexistent")
    check("release nonexistent returns False", not released)

    # 14. Release session locks
    mgr6 = LockManager()
    mgr6.acquire_write_lock("p1", "sess_s", "user_s")
    mgr6.acquire_write_lock("p2", "sess_s", "user_s")
    mgr6.acquire_read_lock("p3", "sess_s", "user_s")
    count = mgr6.release_session_locks("sess_s")
    check("releases all session locks", count == 3)

    # ===============================================================
    # Lock Expiry
    # ===============================================================
    print("\n=== Lock Expiry ===")
    mgr7 = LockManager()

    # 15. Expired locks cleaned up
    with patch('time.time', return_value=100.0):
        lock_exp = mgr7.acquire_write_lock("page_exp", "sess_e", "user_e", ttl_seconds=10)
    # Fast-forward past TTL
    with patch('time.time', return_value=111.0):
        check("lock is expired", lock_exp.is_expired)
        cleaned = mgr7.cleanup_expired()
        check("expired lock cleaned", cleaned > 0)
        # Verify no longer blocking
        try:
            mgr7.acquire_write_lock("page_exp", "sess_new2", "user_new2")
            check("expired lock no longer blocks", True)
        except LockError:
            check("expired lock no longer blocks", False, "should be released")

    # 16. Heartbeat on expired lock releases it
    with patch('time.time', return_value=200.0):
        lock_hb = mgr7.acquire_write_lock("page_hb2", "sess_h", "user_h", ttl_seconds=10)
    with patch('time.time', return_value=220.0):
        result = mgr7.heartbeat(lock_hb.lock_id)
        check("heartbeat on expired lock returns None", result is None)

    # ===============================================================
    # is_resource_locked
    # ===============================================================
    print("\n=== Resource Locked Check ===")
    mgr8 = LockManager()
    mgr8.acquire_write_lock("locked_page", "sess_lock", "user_lock")
    check("resource_locked detects lock", mgr8.is_resource_locked("locked_page"))
    check("unlocked resource returns false", not mgr8.is_resource_locked("free_page"))
    # Same session should not block itself
    check("same session not blocked",
          not mgr8.is_resource_locked("locked_page", session_id="sess_lock"))

    # ===============================================================
    # Stats
    # ===============================================================
    print("\n=== Stats ===")
    mgr9 = LockManager()
    mgr9.acquire_read_lock("r1", "s1", "u1")
    mgr9.acquire_write_lock("w1", "s2", "u2")
    mgr9.acquire_session_lock("c1", "s3", "u3")
    stats = mgr9.get_stats()
    check("has total_locks", "total_locks" in stats)
    check("has active_locks", stats["active_locks"] == 3)
    check("has by_type", "by_type" in stats)
    check("read count", stats["by_type"]["read"] == 1)
    check("write count", stats["by_type"]["write"] == 1)
    check("session count", stats["by_type"]["session"] == 1)

    # ===============================================================
    # LockError
    # ===============================================================
    print("\n=== LockError ===")
    e = LockError("PAGE_LOCKED", "Page locked by Alice", details={"page_id": "p1"})
    check("error code", e.code == "PAGE_LOCKED")
    check("error http_status", e.http_status == 409)
    check("error has details", "page_id" in e.details)

    # ===============================================================
    # Default TTLs
    # ===============================================================
    print("\n=== Default TTLs ===")
    check("read TTL 60s", DEFAULT_READ_TTL == 60)
    check("write TTL 900s", DEFAULT_WRITE_TTL == 900)
    check("session TTL 3600s", DEFAULT_SESSION_TTL == 3600)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if failures:
        print("FAILURES:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
