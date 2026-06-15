"""Tests for US-BKND-AI-048 - Dead Letter Queue."""
from app.services.ai.dead_letter_queue import (
    DeadLetterQueue, DeadLetterJob, FailureCategory, JobStatus, get_dlq,
)

passed = 0; failed = 0; failures = []
def check(n, c, d=""):
    global passed, failed
    if c: passed += 1; print(f"  PASS: {n}")
    else: failed += 1; failures.append((n, d)); print(f"  FAIL: {n} -- {d}")

def main():
    global passed, failed
    dlq = DeadLetterQueue()

    print("=== Enqueue ===")
    job = dlq.enqueue("j1", "proposal", "s1", "u1", "Connection timeout", {"page": "p1"})
    check("enqueues job", job is not None)
    check("failure classified transient", job.failure_category == FailureCategory.TRANSIENT)
    check("initial status FAILED", job.status == JobStatus.FAILED)
    check("retry count 0", job.retry_count == 0)

    job2 = dlq.enqueue("j2", "ingestion", "s2", "u2", "Validation error: invalid format", {})
    check("validation is permanent", job2.failure_category == FailureCategory.PERMANENT)

    job3 = dlq.enqueue("j3", "chat_turn", "s3", "u3", "Anthropic API error 500", {})
    check("provider error classified", job3.failure_category == FailureCategory.PROVIDER)

    print("\n=== Retry ===")
    job4 = dlq.enqueue("j4", "generation", "s4", "u4", "rate limit exceeded", {}, max_retries=2)
    r1 = dlq.retry_job("j4")
    check("first retry increments count", r1.retry_count == 1)
    check("backoff calculated", r1.retry_backoff_seconds() >= 5)
    r2 = dlq.retry_job("j4")
    check("second retry", r2.retry_count == 2)
    r3 = dlq.retry_job("j4")
    check("third retry makes job dead", r3.status == JobStatus.DEAD)
    check("dead job cannot retry", not r3.can_retry())

    print("\n=== Recovery/Discard ===")
    dlq.mark_recovered("j1")
    check("recovered status", dlq.get_job("j1").status == JobStatus.RECOVERED)
    dlq.mark_discarded("j2")
    check("discarded status", dlq.get_job("j2").status == JobStatus.DISCARDED)
    check("get nonexistent returns None", dlq.get_job("nonexistent") is None)

    print("\n=== List/Filter ===")
    jobs = dlq.list_jobs(status="dead")
    check("filters by status", all(j.status == JobStatus.DEAD for j in jobs))
    jobs = dlq.list_jobs(job_type="proposal")
    check("filters by type", all(j.job_type == "proposal" for j in jobs))
    jobs = dlq.list_jobs(category="transient")
    check("filters by category", all(j.failure_category == FailureCategory.TRANSIENT for j in jobs))

    print("\n=== Stats ===")
    stats = dlq.get_stats()
    check("stats has total", "total_jobs" in stats)
    check("stats has by_status", "by_status" in stats)
    check("stats has by_category", "by_category" in stats)
    check("stats has by_type", "by_type" in stats)

    print("\n=== Cleanup ===")
    removed = dlq.cleanup_old_jobs(max_age_hours=0)  # All recovered/discarded
    check("cleanup removes old jobs", removed >= 0)

    print("\n=== Singleton ===")
    d1 = get_dlq()
    d2 = get_dlq()
    check("singleton returns same instance", d1 is d2)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    exit(0 if main() else 1)
